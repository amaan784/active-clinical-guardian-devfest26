import os
import requests
import json
from dotenv import load_dotenv

load_dotenv()

def test_k2_think():
    print("Connecting to K2 Think...")
    
    # Setup Configuration
    api_key = os.getenv("K2_API_KEY")
    url = "https://api.k2think.ai/v1/chat/completions"
    
    headers = {
        "accept": "application/json",
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": "MBZUAI-IFM/K2-Think-v2",
        "messages": [
            {
                "role": "user",
                "content": "What is 2 + 2? Answer briefly."
            }
        ],
        "stream": False
    }

    try:
        # Make Request
        print("   Sending request...")
        response = requests.post(url, headers=headers, json=payload)
        
        # Handle Response
        if response.status_code == 200:
            data = response.json()
            content = data['choices'][0]['message']['content']
            print(f"SUCCESS: {content}")
        else:
            print(f"FAILED: Status {response.status_code}")
            print(f"   Response: {response.text}")

    except Exception as e:
        print(f"ERROR: {e}")

if __name__ == "__main__":
    test_k2_think()