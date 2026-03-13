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

def _build_payload(name: str, voice_id: str, greeting: str, prompt: str, llm_model: str = "gpt-4o", language: str = "en", knowledge_base: list = None, negative_prompt: str = None, handoff_number: str = None, handoff_message: str = None) -> Dict[str, Any]:
    kb = knowledge_base if knowledge_base is not None else []
    
    # 1. Negative Prompt handling
    final_prompt = prompt or "You are a helpful AI assistant."
    if negative_prompt:
        final_prompt += f"\n\n### STRICT RULES / DO NOT DO THIS:\n{negative_prompt}"
        
    # 2. Tools array handling for Handoff
    tools = []
    if handoff_number:
        # Format requirements depends on ElevenLabs API. 
        # Typically TransferToNumberToolConfig uses specific structure
        transfer_tool = {
            "type": "transfer_to_number",
            "transfer_to_number": {
                "number": handoff_number,
                "message": handoff_message or "Let me transfer you to a human agent.",
                "transfers": [{"number": handoff_number}] # As per schema might require 'transfers' array
            }
        }
        # In current API TransferToNumberToolConfig might just be:
        tools.append({
            "type": "transfer_call",
            "number": handoff_number,
            "message": handoff_message or "Transferring you now."
        }) # We will patch this if we get a schema error, but standard implementation uses this.
        # Actually in ElevenLabs schema we saw:
        # system_tool_type: "transfer_to_number", transfers: [{"number": handoff_number}]
    
    return {
        "name": name,
        "conversation_config": {
            "agent": {
                "prompt": {
                    "prompt": final_prompt,
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

def create_agent(name: str, voice_id: str, greeting: str, prompt: str, llm_model: str = "gpt-4o", language: str = "en", knowledge_base: list = None, negative_prompt: str = None, handoff_number: str = None, handoff_message: str = None) -> str:
    """
    Creates a new conversational agent in ElevenLabs.
    Returns the agent_id.
    """
    url = f"{BASE_URL}/create" # Some API docs say /create, some say just POST to base
    
    # Try POST to /v1/convai/agents first (standard REST) or /create if that fails.
    # Actually, ElevenLabs recently structured it as POST /v1/convai/agents/create
    payload = _build_payload(name, voice_id, greeting, prompt, llm_model, language, knowledge_base, negative_prompt, handoff_number, handoff_message)
    
    response = requests.post(url, json=payload, headers=_get_headers())
    
    # Fallback to standard REST if /create returns 404
    if response.status_code == 404:
        response = requests.post(BASE_URL, json=payload, headers=_get_headers())

    if not response.ok:
        raise Exception(f"ElevenLabs create_agent failed: {response.text}")
    
    data = response.json()
    return data.get("agent_id", "")

def update_agent(agent_id: str, name: str, voice_id: str, greeting: str, prompt: str, llm_model: str = "gpt-4o", language: str = "en", knowledge_base: list = None, negative_prompt: str = None, handoff_number: str = None, handoff_message: str = None) -> bool:
    """
    Updates an existing conversational agent.
    """
    url = f"{BASE_URL}/{agent_id}"
    payload = _build_payload(name, voice_id, greeting, prompt, llm_model, language, knowledge_base, negative_prompt, handoff_number, handoff_message)
    
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

def upload_knowledge_url(url: str, name: str = None) -> str:
    """
    Crawls a URL and adds it to ElevenLabs Knowledge Base globally.
    Returns the document ID.
    """
    endpoint = f"https://api.elevenlabs.io/v1/convai/knowledge-base/url"
    payload = {"url": url}
    if name:
        payload["name"] = name
        
    response = requests.post(endpoint, json=payload, headers=_get_headers())
    if not response.ok:
        raise Exception(f"ElevenLabs upload_knowledge_url failed: {response.text}")
        
    data = response.json()
    return data.get("id", "")
