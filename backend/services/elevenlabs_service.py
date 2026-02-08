"""
Synapse 2.0 ElevenLabs Service
Voice I/O for transcription and text-to-speech interruptions
"""

import logging
import asyncio
import base64
from typing import Optional, Callable, AsyncGenerator
import json
import io

from config import get_settings

logger = logging.getLogger(__name__)

# Conditional imports
try:
    from elevenlabs.client import ElevenLabs
    from elevenlabs.realtime_speech_to_text import RealtimeSpeechToText
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
    - Voice transcription (Scribe)
    - Text-to-speech with low-latency streaming (Turbo v2.5)
    - Real-time voice interruptions
    """

    def __init__(self):
        self.settings = get_settings()
        self._client = None
        self._tts_ws = None

        # Voice settings
        self.voice_id = self.settings.elevenlabs_voice_id
        self.model_id = "eleven_turbo_v2_5"  # Low-latency model

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
            self._client = ElevenLabs(api_key=self.settings.elevenlabs_api_key)
            logger.info("ElevenLabs client initialized")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize ElevenLabs: {e}")
            return False

    async def close(self) -> None:
        """Close connections"""
        if self._tts_ws:
            await self._tts_ws.close()

    async def transcribe_audio(
        self,
        audio_data: bytes,
        language: str = "en"
    ) -> Optional[str]:
        """
        Transcribe audio using ElevenLabs Scribe

        Args:
            audio_data: Raw audio bytes (WAV/MP3 format)
            language: Language code

        Returns:
            Transcribed text or None
        """
        if not self._client:
            # Mock transcription for demo
            logger.info("Mock transcription mode")
            return None
        
        try:
            # Wrap the raw bytes in a file-like object
            audio_file = io.BytesIO(audio_data)
            audio_file.name = "audio.wav"  # vital: helps API detect format

            # Call the API with the correct 'file' argument
            result = await asyncio.to_thread(
                self._client.speech_to_text.convert,
                file=audio_file,     
                model_id="scribe_v2",
            )
            return result.text

        except Exception as e:
            logger.error(f"Transcription error: {e}")
            return None
    

    async def text_to_speech_stream(
        self,
        text: str,
        on_audio_chunk: Callable[[bytes], None]
    ) -> bool:
        """
        Stream text-to-speech audio using WebSocket for minimal latency

        Args:
            text: Text to convert to speech
            on_audio_chunk: Callback for each audio chunk

        Returns:
            Success status
        """
        if not WEBSOCKETS_AVAILABLE:
            logger.warning("WebSockets not available for TTS streaming")
            return False

        if not self.settings.elevenlabs_api_key:
            logger.info(f"Mock TTS: Would speak: {text}")
            return True

        try:
            async with websockets.connect(
                self.tts_ws_url,
                extra_headers={"xi-api-key": self.settings.elevenlabs_api_key}
            ) as ws:
                # Send initial configuration
                await ws.send(json.dumps({
                    "text": " ",
                    "voice_settings": {
                        "stability": 0.5,
                        "similarity_boost": 0.75,
                    },
                    "xi_api_key": self.settings.elevenlabs_api_key,
                }))

                # Send the actual text
                await ws.send(json.dumps({
                    "text": text,
                    "try_trigger_generation": True,
                }))

                # Send end of stream signal
                await ws.send(json.dumps({
                    "text": "",
                }))

                # Receive audio chunks
                async for message in ws:
                    data = json.loads(message)
                    if "audio" in data and data["audio"]:
                        audio_bytes = base64.b64decode(data["audio"])
                        on_audio_chunk(audio_bytes)
                    if data.get("isFinal"):
                        break

                return True

        except Exception as e:
            logger.error(f"TTS streaming error: {e}")
            return False

    async def speak_interruption(
        self,
        warning_text: str
    ) -> AsyncGenerator[bytes, None]:
        """
        Generate speech for clinical interruption

        This is optimized for low-latency delivery of urgent warnings

        Args:
            warning_text: The warning to speak

        Yields:
            Audio chunks as bytes
        """
        logger.info(f"Generating interruption speech: {warning_text}")

        if not self._client or not self.settings.elevenlabs_api_key:
            # Return empty for mock mode
            logger.info(f"Mock interruption: {warning_text}")
            return

        try:
            audio_generator = await asyncio.to_thread(
                self._client.text_to_speech.convert,
                voice_id=self.voice_id,
                model_id=self.model_id,
                text=warning_text,
                output_format="mp3_44100_128",
                stream=True,
                voice_settings={
                    "stability": 0.5,
                    "similarity_boost": 0.75,
                    "style": 0.0,
                    "use_speaker_boost": True,
                },
            )

            for chunk in audio_generator:
                yield chunk

        except Exception as e:
            logger.error(f"Interruption speech error: {e}")

    async def get_available_voices(self) -> list[dict]:
        """Get list of available voices"""
        if not self._client:
            return [
                {"voice_id": "21m00Tcm4TlvDq8ikWAM", "name": "Rachel (Default)"},
                {"voice_id": "AZnzlk1XvdvUeBnXmlld", "name": "Domi"},
                {"voice_id": "EXAVITQu4vr4xnSDxMaL", "name": "Bella"},
            ]

        try:
            voices = await asyncio.to_thread(self._client.voices.get_all)
            return [
                {"voice_id": v.voice_id, "name": v.name}
                for v in voices.voices
            ]
        except Exception as e:
            logger.error(f"Error getting voices: {e}")
            return []


class AudioStreamProcessor:
    """
    Processes incoming audio stream for real-time transcription

    Handles buffering, silence detection, and chunking
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        silence_threshold: float = 0.01,
        silence_duration: float = 1.0,
    ):
        self.sample_rate = sample_rate
        self.silence_threshold = silence_threshold
        self.silence_duration = silence_duration

        self._buffer: list[bytes] = []
        self._silence_frames = 0

    def add_chunk(self, audio_chunk: bytes) -> Optional[bytes]:
        """
        Add audio chunk to buffer

        Returns complete utterance when silence is detected.
        Handles both raw PCM and compressed (webm/opus) audio formats.
        """
        self._buffer.append(audio_chunk)

        # Simple silence detection based on amplitude (raw PCM only)
        # For compressed audio (webm/opus from browser), fall back to chunk counting
        try:
            import numpy as np
            # Only attempt PCM decode if buffer size is a multiple of 2 (int16)
            if len(audio_chunk) % 2 == 0 and len(audio_chunk) >= 2:
                audio_array = np.frombuffer(audio_chunk, dtype=np.int16)
                amplitude = np.abs(audio_array).mean() / 32768.0

                if amplitude < self.silence_threshold:
                    self._silence_frames += 1
                else:
                    self._silence_frames = 0

                # Check if we've had enough silence to segment
                frames_for_duration = int(self.silence_duration * self.sample_rate / max(len(audio_chunk), 1))
                if self._silence_frames >= frames_for_duration and len(self._buffer) > 1:
                    complete_audio = b"".join(self._buffer)
                    self._buffer.clear()
                    self._silence_frames = 0
                    return complete_audio
            else:
                # Compressed audio — use chunk-count-based buffering
                if len(self._buffer) >= 12:  # ~3 seconds at 250ms chunks
                    complete_audio = b"".join(self._buffer)
                    self._buffer.clear()
                    return complete_audio

        except (ImportError, ValueError):
            # Fallback: buffer and return periodically
            if len(self._buffer) >= 12:  # ~3 seconds at 250ms chunks
                complete_audio = b"".join(self._buffer)
                self._buffer.clear()
                return complete_audio

        return None

    def flush(self) -> Optional[bytes]:
        """Flush remaining buffer"""
        if self._buffer:
            complete_audio = b"".join(self._buffer)
            self._buffer.clear()
            return complete_audio
        return None
