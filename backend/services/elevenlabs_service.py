"""
The Active Clinical Guardian - ElevenLabs Service
Voice I/O for transcription and text-to-speech interruptions
"""

import logging
import asyncio
import base64
import io
from typing import Optional, Callable, AsyncGenerator

from config import get_settings

logger = logging.getLogger(__name__)

# SDK imports (elevenlabs v2.34.0)
try:
    from elevenlabs import ElevenLabs, RealtimeEvents
    from elevenlabs.realtime.scribe import AudioFormat, CommitStrategy
    from elevenlabs.realtime.connection import RealtimeConnection
    ELEVENLABS_AVAILABLE = True
except ImportError:
    ELEVENLABS_AVAILABLE = False
    logger.warning("ElevenLabs SDK not available")


class ManagedScribeConnection:
    """
    Wrapper around RealtimeConnection that handles:
    - Lazy connection: only opens the Scribe WebSocket on the first audio chunk
    - Auto-reconnect: if the server closes (e.g. inactivity timeout), reconnects
      transparently on the next send
    - Clean close: caller calls close() when the session ends

    IMPORTANT: Only ONE ElevenLabs Scribe connection may be active at a time.
    The asyncio.Lock + cooldown prevents the flood of concurrent connect() calls
    that previously caused rate-limiting.
    """

    # Cooldown (seconds) after a failed send before we attempt to reconnect
    _RECONNECT_COOLDOWN = 3.0

    def __init__(self, client: "ElevenLabs", on_text: Callable[[str, bool], None]):
        self._client = client
        self._on_text = on_text
        self._connection: Optional["RealtimeConnection"] = None
        self._closed = False
        self._lock = asyncio.Lock()
        self._reconnect_after: float = 0  # monotonic timestamp

    async def _ensure_connected(self) -> Optional["RealtimeConnection"]:
        """Open (or reopen) the Scribe connection if needed."""
        if self._closed:
            return None

        # Fast path: already have a live connection
        if self._connection is not None:
            return self._connection

        # Cooldown: don't reconnect too quickly after a failure
        now = asyncio.get_event_loop().time()
        if now < self._reconnect_after:
            return None

        # Slow path: acquire lock so only one connect() runs at a time
        async with self._lock:
            # Re-check after acquiring lock (another coroutine may have connected)
            if self._connection is not None:
                return self._connection
            if self._closed:
                return None

            try:
                logger.info("Opening Scribe connection...")
                connection: RealtimeConnection = await self._client.speech_to_text.realtime.connect({
                    "model_id": "scribe_v2_realtime",
                    "audio_format": AudioFormat.PCM_16000,
                    "sample_rate": 16000,
                    "commit_strategy": CommitStrategy.VAD,
                    "language_code": "en",
                })

                on_text = self._on_text  # capture for closures

                def on_session_started(data):
                    logger.info(f"Scribe session started (session_id={data.get('session_id', '?')})")

                def on_partial_transcript(data):
                    text = data.get("text", "") if isinstance(data, dict) else getattr(data, "text", "")
                    if text:
                        asyncio.create_task(on_text(text, False))

                def on_committed_transcript(data):
                    text = data.get("text", "") if isinstance(data, dict) else getattr(data, "text", "")
                    if text:
                        asyncio.create_task(on_text(text, True))

                def on_error(error):
                    logger.error(f"Scribe error: {error}")

                def on_close():
                    logger.info("Scribe connection closed by server")

                connection.on(RealtimeEvents.SESSION_STARTED, on_session_started)
                connection.on(RealtimeEvents.PARTIAL_TRANSCRIPT, on_partial_transcript)
                connection.on(RealtimeEvents.COMMITTED_TRANSCRIPT, on_committed_transcript)
                connection.on(RealtimeEvents.ERROR, on_error)
                connection.on(RealtimeEvents.CLOSE, on_close)

                self._connection = connection
                logger.info("ElevenLabs Scribe v2 realtime stream connected")
                return connection

            except Exception as e:
                logger.error(f"Failed to open Scribe connection: {e}")
                self._reconnect_after = asyncio.get_event_loop().time() + self._RECONNECT_COOLDOWN
                return None

    async def send(self, audio_data: bytes) -> None:
        """Send PCM audio; opens/reopens connection as needed."""
        conn = await self._ensure_connected()
        if conn is None:
            return
        try:
            audio_b64 = base64.b64encode(audio_data).decode("ascii")
            await conn.send({"audio_base_64": audio_b64})
        except Exception as e:
            logger.error(f"Error sending audio chunk: {e}")
            # Mark connection as dead so next send will reconnect (after cooldown)
            self._connection = None
            self._reconnect_after = asyncio.get_event_loop().time() + self._RECONNECT_COOLDOWN

    async def close(self) -> None:
        """Permanently close this managed connection."""
        self._closed = True
        if self._connection is not None:
            try:
                await self._connection.close()
            except Exception as e:
                logger.error(f"Error closing Scribe connection: {e}")
            self._connection = None


class ElevenLabsService:
    """
    ElevenLabs integration for:
    - Voice transcription (Scribe v2 Realtime)
    - Text-to-speech with low-latency streaming (Turbo v2.5)
    - Real-time voice interruptions

    Architecture note:
    - The service holds a shared ElevenLabs *client* (API key, HTTP pool).
    - Each WebSocket session gets its own ManagedScribeConnection via
      start_transcription_stream(), which returns the managed wrapper.
    - The wrapper handles lazy connect and auto-reconnect.
    - The caller (main.py) owns the connection lifecycle.
    """

    def __init__(self):
        self.settings = get_settings()
        self._client: Optional[ElevenLabs] = None

        # Voice settings
        self.voice_id = self.settings.elevenlabs_voice_id
        self.tts_model_id = "eleven_turbo_v2_5"

    async def initialize(self) -> bool:
        """Initialize ElevenLabs client"""
        if not ELEVENLABS_AVAILABLE:
            logger.error("ElevenLabs SDK not available")
            return False

        if not self.settings.elevenlabs_api_key:
            logger.warning("ElevenLabs API key not configured")
            return True

        try:
            self._client = ElevenLabs(api_key=self.settings.elevenlabs_api_key)
            logger.info("ElevenLabs client initialized")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize ElevenLabs: {e}")
            return False

    async def close(self) -> None:
        """Close the shared client (connections are closed by callers)"""
        self._client = None

    # ──────────────────────────────────────────────────────────────────────────
    #  Real-time Scribe Transcription (Streaming)
    # ──────────────────────────────────────────────────────────────────────────

    async def start_transcription_stream(
        self,
        on_text: Callable[[str, bool], None],
    ) -> Optional[ManagedScribeConnection]:
        """
        Create a managed Scribe v2 realtime connection wrapper.

        The actual WebSocket to ElevenLabs is opened **lazily** on the first
        audio chunk, avoiding the 15-second inactivity timeout that occurs
        when the connection is opened before the user starts speaking.

        If the server closes the connection (e.g. silence timeout), the
        wrapper will automatically reconnect on the next audio chunk.

        Returns a ManagedScribeConnection (or None if not configured).
        """
        if not self._client:
            logger.error("ElevenLabs not configured — cannot start transcription")
            return None

        return ManagedScribeConnection(self._client, on_text)

    @staticmethod
    async def send_audio_chunk(
        connection: Optional[ManagedScribeConnection],
        audio_data: bytes,
    ) -> None:
        """
        Send a PCM audio chunk via the managed Scribe connection.
        The connection is opened lazily on the first call.
        """
        if connection is None:
            return
        await connection.send(audio_data)

    @staticmethod
    async def close_transcription_stream(
        connection: Optional[ManagedScribeConnection],
    ) -> None:
        """Gracefully close a managed Scribe connection."""
        if connection is None:
            return
        await connection.close()

    # ──────────────────────────────────────────────────────────────────────────
    #  Legacy / Fallback Transcription (REST)
    # ──────────────────────────────────────────────────────────────────────────

    async def transcribe_audio(self, audio_data: bytes, language: str = "en") -> Optional[str]:
        """One-off transcription via REST API (Scribe v2 batch)"""
        if not self._client:
            return None

        try:
            audio_file = io.BytesIO(audio_data)
            audio_file.name = "audio.wav"

            result = await asyncio.to_thread(
                self._client.speech_to_text.convert,
                file=audio_file,
                model_id="scribe_v2",
            )
            return result.text
        except Exception as e:
            logger.error(f"Transcription error: {e}")
            return None

    # ──────────────────────────────────────────────────────────────────────────
    #  Text-to-Speech (TTS)
    # ──────────────────────────────────────────────────────────────────────────

    async def speak_interruption(self, warning_text: str) -> AsyncGenerator[bytes, None]:
        """
        Generate low-latency interruption speech.

        SDK v2.34.0 exposes two TTS methods:
          - convert()  → returns full audio (bytes iterator)
          - stream()   → returns a streaming iterator (lower TTFB)
        We use stream() for minimal latency on safety alerts.
        """
        if not self._client:
            logger.error("ElevenLabs not configured — cannot generate speech")
            return

        try:
            audio_iterator = await asyncio.to_thread(
                self._client.text_to_speech.stream,
                voice_id=self.voice_id,
                model_id=self.tts_model_id,
                text=warning_text,
                output_format="mp3_44100_128",
            )

            for chunk in audio_iterator:
                yield chunk

        except Exception as e:
            logger.error(f"Interruption speech error: {e}")

    async def get_available_voices(self) -> list[dict]:
        """Get list of available voices"""
        if not self._client:
            return []
        try:
            voices = await asyncio.to_thread(self._client.voices.get_all)
            return [{"voice_id": v.voice_id, "name": v.name} for v in voices.voices]
        except Exception:
            return []


class AudioStreamProcessor:
    """
    Thin pass-through kept for backward compatibility.
    With Scribe v2 realtime, buffering/silence-detection is handled
    server-side by ElevenLabs (CommitStrategy.VAD).
    """

    def __init__(self, sample_rate: int = 16000):
        self._buffer: list[bytes] = []

    def add_chunk(self, chunk: bytes) -> bytes:
        return chunk