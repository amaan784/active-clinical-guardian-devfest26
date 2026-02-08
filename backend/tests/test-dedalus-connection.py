import asyncio
import os
from dotenv import load_dotenv
from dedalus_labs import AsyncDedalus, DedalusRunner

# Load environment variables (DEDALUS_API_KEY)
load_dotenv()

async def test_dedalus():
    print("Connecting to Dedalus...")
    
    try:
        # Initialize Client
        # Automatically looks for DEDALUS_API_KEY in environment
        client = AsyncDedalus()
        runner = DedalusRunner(client)

        # Run a Simple Agent Task
        # We use a small model to test the connection quickly
        print("   Sending request...")
        result = await runner.run(
            input="Say 'Dedalus Connection Successful' and nothing else.",
            model="openai/gpt-4o-mini" # Dedalus routes this automatically
        )

        # Print Result
        print(f"SUCCESS: {result.final_output}")

    except Exception as e:
        print(f"FAILED: {e}")
        print("   Check if DEDALUS_API_KEY is set in your .env file.")

if __name__ == "__main__":
    asyncio.run(test_dedalus())