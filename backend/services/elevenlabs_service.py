
"""
Synapse 2.0 ElevenLabs Service
Voice I/O for transcription and text-to-speech interruptions
"""

import logging
import asyncio
import base64
import io
import json
from typing import Optional, Callable, AsyncGenerator

from config import get_settings

logger = logging.getLogger(__name__)

# --- CORRECTED IMPORTS PER DOCUMENTATION ---
try:
    # We import directly from 'elevenlabs' as the docs suggest
    from elevenlabs import ElevenLabs, RealtimeEvents
    ELEVENLABS_AVAILABLE = True
except ImportError:
    ELEVENLABS_AVAILABLE = False
    logger.warning("ElevenLabs SDK not available")

try:
    import websockets
    WEBSOCKETS_AVAILABLE = True
except ImportError:
    WEBSOCKETS_AVAILABLE = False
    logger.warning("websockets library not available")


class ElevenLabsService:
    """
    ElevenLabs integration for:
    - Voice transcription (Scribe v2 Realtime)
    - Text-to-speech with low-latency streaming (Turbo v2.5)
    - Real-time voice interruptions
    """

    def __init__(self):
        self.settings = get_settings()
        self._client: Optional[ElevenLabs] = None
        self._transcript_connection = None
        
        # Voice settings
        self.voice_id = self.settings.elevenlabs_voice_id
        self.model_id = "eleven_turbo_v2_5"
        
        # TTS WebSocket URL
        self.tts_ws_url = f"wss://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}/stream-input?model_id={self.model_id}"

    async def initialize(self) -> bool:
        """Initialize ElevenLabs client"""
        if not ELEVENLABS_AVAILABLE:
            logger.warning("ElevenLabs not available, using mock mode")
            return True

        if not self.settings.elevenlabs_api_key:
            logger.warning("ElevenLabs API key not configured")
            return True

        try:
            # Initialize the client exactly as shown in docs
            self._client = ElevenLabs(api_key=self.settings.elevenlabs_api_key)
            logger.info("ElevenLabs client initialized")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize ElevenLabs: {e}")
            return False

    async def close(self) -> None:
        """Close connections"""
        if self._transcript_connection:
            await self._transcript_connection.close()
            self._transcript_connection = None

    # ──────────────────────────────────────────────────────────────────────────
    #  Real-time Scribe Transcription (Streaming)
    # ──────────────────────────────────────────────────────────────────────────
    async def start_transcription_stream(self, on_text: Callable[[str, bool], None]):
        """
        Start a persistent WebSocket connection for Scribe v2 transcription.
        """
        if not self._client:
            return

        try:
            # FIX: Call connect() directly. Do NOT use asyncio.to_thread here.
            # The documentation confirms this method is awaitable.
            self._transcript_connection = await self._client.speech_to_text.realtime.connect(
                model_id="scribe_v2_realtime",
            )

            def on_session_started(data):
                logger.info(f"Scribe session started: {data}")

            def on_partial_transcript(data):
                # Data comes in as a dict per the SDK
                text = data.get('text', '')
                if text:
                    if asyncio.iscoroutinefunction(on_text):
                        asyncio.create_task(on_text(text, False))
                    else:
                        on_text(text, False)

            def on_committed_transcript(data):
                text = data.get('text', '')
                if text:
                    if asyncio.iscoroutinefunction(on_text):
                        asyncio.create_task(on_text(text, True))
                    else:
                        on_text(text, True)

            def on_error(error):
                logger.error(f"Scribe Error: {error}")

            def on_close():
                logger.info("Scribe connection closed")

            # Register handlers using the imported RealtimeEvents enum
            self._transcript_connection.on(RealtimeEvents.SESSION_STARTED, on_session_started)
            self._transcript_connection.on(RealtimeEvents.PARTIAL_TRANSCRIPT, on_partial_transcript)
            self._transcript_connection.on(RealtimeEvents.COMMITTED_TRANSCRIPT, on_committed_transcript)
            self._transcript_connection.on(RealtimeEvents.ERROR, on_error)
            self._transcript_connection.on(RealtimeEvents.CLOSE, on_close)
            
            logger.info("ElevenLabs Scribe v2 Stream connected")

        except Exception as e:
            logger.error(f"Failed to start transcription stream: {e}")

    async def send_audio_chunk(self, audio_data: bytes):
        """Push a chunk of audio bytes to the active Scribe connection."""
        if not self._client or not self._transcript_connection:
            return

        try:
            # SDK usually exposes a method to send audio bytes directly
            await self._transcript_connection.send_audio(audio_data)
        except Exception as e:
            logger.error(f"Error sending audio chunk: {e}")

    # ──────────────────────────────────────────────────────────────────────────
    #  Legacy / Fallback Transcription
    # ──────────────────────────────────────────────────────────────────────────

    async def transcribe_audio(self, audio_data: bytes, language: str = "en") -> Optional[str]:
        """One-off transcription (REST API)"""
        if not self._client:
            return None

        try:
            audio_file = io.BytesIO(audio_data)
            audio_file.name = "audio.wav"

            # This is the blocking REST call
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
        """Generate low-latency interruption speech"""
        if not self._client:
            return

        try:
            audio_generator = await asyncio.to_thread(
                self._client.text_to_speech.convert,
                voice_id=self.voice_id,
                model_id=self.model_id,
                text=warning_text,
                stream=True, # Critical for speed
            )

            for chunk in audio_generator:
                yield chunk

        except Exception as e:
            logger.error(f"Interruption speech error: {e}")

    # ... Rest of helper classes (AudioStreamProcessor) remain the same ...
    async def get_available_voices(self) -> list[dict]:
        if not self._client: return []
        try:
            voices = await asyncio.to_thread(self._client.voices.get_all)
            return [{"voice_id": v.voice_id, "name": v.name} for v in voices.voices]
        except Exception:
            return []

class AudioStreamProcessor:
    def __init__(self, sample_rate=16000):
        self._buffer = []
    
    def add_chunk(self, chunk):
        return chunk