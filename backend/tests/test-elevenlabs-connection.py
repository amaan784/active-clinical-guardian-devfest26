import os
from dotenv import load_dotenv
from elevenlabs.client import ElevenLabs
from elevenlabs.play import play

load_dotenv()

def test_elevenlabs():
    print("Connecting to ElevenLabs...")

    try:
        # Initialize Client
        elevenlabs = ElevenLabs(
            api_key=os.getenv("ELEVENLABS_API_KEY"),
        )

        # Generate Audio Stream
        print("   Generating audio...")
        audio_stream = elevenlabs.text_to_speech.convert(
            text="The first move is what sets everything in motion.",
            voice_id="JBFqnCBsd6RMkjVDRZzb",
            model_id="eleven_multilingual_v2",
            output_format="mp3_44100_128",
        )

        play(audio=audio_stream, use_ffmpeg=False)
        print("SUCCESS: Audio generated and played successfully.")

    except Exception as e:
        print(f"FAILED: {e}")
        print("   Check your ELEVENLABS_API_KEY.")

if __name__ == "__main__":
    test_elevenlabs()