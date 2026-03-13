import os, requests, json
from dotenv import load_dotenv
load_dotenv('.env')
key = os.getenv('ELEVENLABS_API_KEY')
print("Testing /v1/convai/agents with empty payload to see schema error")
res = requests.post("https://api.elevenlabs.io/v1/convai/agents/create", json={"name": "test"}, headers={"xi-api-key": key, "content-type": "application/json"})
print(res.text)
