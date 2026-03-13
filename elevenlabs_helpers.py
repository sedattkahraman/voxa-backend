import os
import requests
from typing import Optional, Dict, Any

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
BASE_URL = "https://api.elevenlabs.io/v1/convai/agents"

def _get_headers() -> Dict[str, str]:
    if not ELEVENLABS_API_KEY:
        raise ValueError("ELEVENLABS_API_KEY is not set")
    return {
        "xi-api-key": ELEVENLABS_API_KEY,
        "Content-Type": "application/json"
    }

def _build_payload(name: str, voice_id: str, greeting: str, prompt: str, llm_model: str = "gpt-4o", language: str = "en", knowledge_base: list = None) -> Dict[str, Any]:
    kb = knowledge_base if knowledge_base is not None else []
    return {
        "name": name,
        "conversation_config": {
            "agent": {
                "prompt": {
                    "prompt": prompt or "You are a helpful AI assistant.",
                    "knowledge_base": kb
                },
                "first_message": greeting or "Hello!",
                "language": language or "en",
                "language_model": {
                    "model_id": llm_model or "gpt-4o"
                }
            },
            "tts": {
                "voice_id": voice_id or "21m00Tcm4TlvDq8ikWAM"
            }
        }
    }

def create_agent(name: str, voice_id: str, greeting: str, prompt: str, llm_model: str = "gpt-4o", language: str = "en", knowledge_base: list = None) -> str:
    """
    Creates a new conversational agent in ElevenLabs.
    Returns the agent_id.
    """
    url = f"{BASE_URL}/create" # Some API docs say /create, some say just POST to base
    
    # Try POST to /v1/convai/agents first (standard REST) or /create if that fails.
    # Actually, ElevenLabs recently structured it as POST /v1/convai/agents/create
    payload = _build_payload(name, voice_id, greeting, prompt, llm_model, language, knowledge_base)
    
    response = requests.post(url, json=payload, headers=_get_headers())
    
    # Fallback to standard REST if /create returns 404
    if response.status_code == 404:
        response = requests.post(BASE_URL, json=payload, headers=_get_headers())

    if not response.ok:
        raise Exception(f"ElevenLabs create_agent failed: {response.text}")
    
    data = response.json()
    return data.get("agent_id", "")

def update_agent(agent_id: str, name: str, voice_id: str, greeting: str, prompt: str, llm_model: str = "gpt-4o", language: str = "en", knowledge_base: list = None) -> bool:
    """
    Updates an existing conversational agent.
    """
    url = f"{BASE_URL}/{agent_id}"
    payload = _build_payload(name, voice_id, greeting, prompt, llm_model, language, knowledge_base)
    
    # Standard REST update is usually PATCH
    response = requests.patch(url, json=payload, headers=_get_headers())
    
    if not response.ok:
        raise Exception(f"ElevenLabs update_agent failed: {response.text}")
    
    return True

def delete_agent(agent_id: str) -> bool:
    """
    Deletes a conversational agent.
    """
    url = f"{BASE_URL}/{agent_id}"
    response = requests.delete(url, headers=_get_headers())
    
    if not response.ok:
        raise Exception(f"ElevenLabs delete_agent failed: {response.text}")
    
    return True
