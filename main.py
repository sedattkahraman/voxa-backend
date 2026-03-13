import os
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form
from pydantic import BaseModel
import httpx
import json
from supabase import create_client, Client
import requests
import stripe
from fastapi.middleware.cors import CORSMiddleware

from integrations.manager import IntegrationManager
from integrations import stripe_helpers
import elevenlabs_helpers
import telnyx
import time

telnyx.api_key = os.getenv("TELNYX_API_KEY", "")

app = FastAPI(title="Voxa Backend Integrations")

# CORS for frontend callback redirects
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In production limit to frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "") # Needs service role key to bypass RLS securely

if SUPABASE_URL and SUPABASE_KEY:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
else:
    print("Warning: Missing SUPABASE ENV variables.")
    supabase = None

class GHLCodeExchangeRequest(BaseModel):
    code: str
    profile_id: str

class SyncAgentRequest(BaseModel):
    profile_id: str
    agent_name: str
    voice_id: str
    greeting_message: str
    system_prompt: str
    llm_model: str = "gpt-4o"
    language: str = "en"
    negative_prompt: str = ""
    handoff_number: str = ""
    handoff_message: str = ""

class AddKnowledgeURLRequest(BaseModel):
    profile_id: str
    url: str
    name: str = ""

class AgentWebhookRequest(BaseModel):
    profile_id: str
    action: str
    payload: dict

@app.post("/api/integrations/ghl/exchange")
async def ghl_exchange(data: GHLCodeExchangeRequest):
    """
    Called by the React frontend after redirecting back from GoHighLevel OAuth.
    It exchanges the 'code' for an access_token using our Client Secret.
    """
    client_id = os.getenv("GHL_CLIENT_ID")
    client_secret = os.getenv("GHL_CLIENT_SECRET")
    
    if not client_id or not client_secret:
        raise HTTPException(status_code=500, detail="GHL credentials not configured on backend.")

    # 1. Exchange logic
    ghl_token_url = "https://services.leadconnectorhq.com/oauth/token"
    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "authorization_code",
        "code": data.code
    }
    
    response = requests.post(ghl_token_url, data=payload)
    if response.status_code != 200:
        return {"success": False, "error": f"GHL API Error: {response.text}"}
    
    tokens = response.json()
    access_token = tokens.get("access_token")
    refresh_token = tokens.get("refresh_token")
    location_id = tokens.get("locationId", "")
    
    # 2. Store in Supabase
    config_data = {
        "oauth": True,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "location_id": location_id,
        "scopes": tokens.get("scope", "")
    }

    if supabase:
        # Check if exists
        existing = supabase.table("integrations").select("*").eq("profile_id", data.profile_id).eq("provider", "go_high_level").execute()
        if len(existing.data) > 0:
            supabase.table("integrations").update({"status": "connected", "config": config_data}).eq("id", existing.data[0]["id"]).execute()
        else:
            supabase.table("integrations").insert({
                "profile_id": data.profile_id,
                "provider": "go_high_level",
                "status": "connected",
                "config": config_data
            }).execute()

    return {"success": True}

@app.post("/api/agent/webhook")
async def agent_webhook(req: AgentWebhookRequest):
    """
    This endpoint is called by your Vapi or ElevenLabs AI agent.
    Example Action: 'check_availability' or 'book_appointment'
    """
    if not supabase:
        raise HTTPException(status_code=500, detail="Database not configured")

    # Fetch user's integrations
    user_integrations = supabase.table('integrations').select('*').eq('profile_id', req.profile_id).execute()
    
    # Find active integrations and dispatch
    # For now, we assume one active integration per user (or loop them)
    results = {}
    for integration in user_integrations.data:
        if integration.get('status') == 'connected':
            try:
                service = IntegrationManager.get_integration(integration['provider'], integration['config'])
                
                # Dynamic action dispatch mapping
                if req.action == "get_available_slots":
                    slots = service.get_available_slots(req.payload.get("start"), req.payload.get("end"))
                    results[integration['provider']] = slots
                elif req.action == "book_appointment":
                    # Map correctly depending on service
                    results[integration['provider']] = "Appointment booked logic triggered."
            except Exception as e:
                results[integration['provider']] = f"Error: {str(e)}"

    return {"success": True, "results": results}

@app.post("/api/agent/sync")
async def sync_elevenlabs_agent(req: SyncAgentRequest):
    """
    Syncs the Supabase agent_settings with ElevenLabs API.
    """
    if not supabase:
        raise HTTPException(status_code=500, detail="Database not configured")
        
    # Check if user already has an elevenlabs_agent_id
    user_agent = supabase.table("agent_settings").select("elevenlabs_agent_id").eq("profile_id", req.profile_id).execute()
    
    if len(user_agent.data) == 0:
        raise HTTPException(status_code=404, detail="Agent settings not found in database for this profile")
        
    existing_id = user_agent.data[0].get("elevenlabs_agent_id")
    
    user_docs = supabase.table("agent_knowledge_base").select("elevenlabs_document_id, file_name").eq("profile_id", req.profile_id).execute()
    kb_items = []
    for doc in user_docs.data:
        kb_items.append({
            "id": doc.get("elevenlabs_document_id"),
            "name": doc.get("file_name"),
            "type": "file"
        })
    
    try:
        if existing_id:
            # Update existing agent
            elevenlabs_helpers.update_agent(
                agent_id=existing_id,
                name=req.agent_name,
                voice_id=req.voice_id,
                greeting=req.greeting_message,
                prompt=req.system_prompt,
                llm_model=req.llm_model,
                language=req.language,
                knowledge_base=kb_items,
                negative_prompt=req.negative_prompt,
                handoff_number=req.handoff_number,
                handoff_message=req.handoff_message
            )
        else:
            # Create a new agent
            new_id = elevenlabs_helpers.create_agent(
                name=req.agent_name,
                voice_id=req.voice_id,
                greeting=req.greeting_message,
                prompt=req.system_prompt,
                llm_model=req.llm_model,
                language=req.language,
                knowledge_base=kb_items,
                negative_prompt=req.negative_prompt,
                handoff_number=req.handoff_number,
                handoff_message=req.handoff_message
            )
            # Save the new ID back to Supabase
            supabase.table("agent_settings").update({"elevenlabs_agent_id": new_id}).eq("profile_id", req.profile_id).execute()
            
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"ElevenLabs sync failed: {str(e)}")

@app.post("/api/agent/knowledge")
async def upload_knowledge(profile_id: str = Form(...), file: UploadFile = File(...)):
    """
    Uploads a document to ElevenLabs Knowledge Base and links it to the user.
    """
    if not supabase:
        raise HTTPException(status_code=500, detail="Database not configured")
    
    content = await file.read()
    try:
        doc_id = elevenlabs_helpers.upload_knowledge_document(content, file.filename, file.content_type)
        res = supabase.table("agent_knowledge_base").insert({
            "profile_id": profile_id,
            "file_name": file.filename,
            "elevenlabs_document_id": doc_id
        }).execute()
        return {"success": True, "document": res.data[0]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/agent/knowledge")
async def get_knowledge(profile_id: str):
    """
    Returns a list of all documents uploaded by the user.
    """
    if not supabase:
        raise HTTPException(status_code=500, detail="Database not configured")
    docs = supabase.table("agent_knowledge_base").select("*").eq("profile_id", profile_id).execute()
    return {"success": True, "documents": docs.data}

@app.delete("/api/agent/knowledge/{doc_id}")
async def delete_knowledge(doc_id: str, profile_id: str):
    """
    Deletes a document from ElevenLabs Knowledge Base and Supabase.
    """
    if not supabase:
        raise HTTPException(status_code=500, detail="Database not configured")
    
    # Verify ownership
    doc = supabase.table("agent_knowledge_base").select("*").eq("id", doc_id).eq("profile_id", profile_id).execute()
    if len(doc.data) == 0:
        raise HTTPException(status_code=404, detail="Document not found")
        
    elevenlabs_doc_id = doc.data[0].get("elevenlabs_document_id")
    
    try:
        elevenlabs_helpers.delete_knowledge_document(elevenlabs_doc_id)
        supabase.table("agent_knowledge_base").delete().eq("id", doc_id).execute()
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class CheckoutRequest(BaseModel):
    plan_id: str
    profile_id: str
    email: str = ""
    success_url: str
    cancel_url: str

@app.post("/api/checkout")
async def create_checkout(req: CheckoutRequest):
    """
    Creates a Stripe checkout session and returns the URL to the frontend.
    """
    try:
        session_data = stripe_helpers.create_checkout_session(
            profile_id=req.profile_id,
            email=req.email,
            plan_id=req.plan_id,
            success_url=req.success_url,
            cancel_url=req.cancel_url
        )
        return {"success": True, "checkout_url": session_data["url"]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/webhooks/stripe")
async def stripe_webhook(request: Request):
    """
    Listens for successful Stripe payments and updates the Supabase credit balance.
    Must use raw body for signature verification.
    """
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    endpoint_secret = os.getenv("STRIPE_WEBHOOK_SECRET") # e.g. whsec_...

    event = None

    try:
        if endpoint_secret:
            event = stripe.Webhook.construct_event(
                payload, sig_header, endpoint_secret
            )
        else:
            # If no webhook secret is configured (e.g. initial dev testing),
            # just parse the JSON directly. DANGEROUS IN PRODUCTION.
            import json
            event = stripe.Event.construct_from(json.loads(payload), stripe.api_key)
    except ValueError as e:
        # Invalid payload
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError as e:
        # Invalid signature
        raise HTTPException(status_code=400, detail="Invalid signature")

    # Handle the event
    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        
        profile_id = session.get("client_reference_id")
        metadata = session.get("metadata", {})
        credits_to_add = int(metadata.get("credits_to_add", 0))

        # Update Supabase Balance securely using Service Role
        if supabase and profile_id and credits_to_add > 0:
            # 1. Get current credits
            user_prof = supabase.table("profiles").select("credits").eq("id", profile_id).execute()
            if len(user_prof.data) > 0:
                current_credits = user_prof.data[0].get("credits", 0)
                new_credits = current_credits + credits_to_add
                
                # 2. Update credits
                supabase.table("profiles").update({"credits": new_credits}).eq("id", profile_id).execute()
                
                # 3. Log transaction
                supabase.table("credit_transactions").insert({
                    "profile_id": profile_id,
                    "amount": credits_to_add,
                    "type": "purchase",
                    "balance_after": new_credits,
                    "description": f"Stripe Checkout: {session.get('id')}"
                }).execute()

    return {"status": "success"}

class ProvisionTelephonyRequest(BaseModel):
    profile_id: str
    agent_id: str

@app.post("/api/telephony/provision")
async def provision_telephony(req: ProvisionTelephonyRequest):
    """
    Called from the frontend to provision a new Australian number 
    and assign it directly to the Voxa agent.
    """
    if not telnyx.api_key:
        raise HTTPException(status_code=500, detail="Telnyx API Keys missing on backend.")
        
    try:
        # 1. Search AU numbers
        available = telnyx.AvailablePhoneNumber.search(
            filter={"country_code": "AU", "features": ["voice"]},
            limit=1
        )
        if not available:
            raise HTTPException(status_code=400, detail="No AU numbers available right now. Try again later.")
            
        target_number = available[0].phone_number
        
        # 2. Purchase the number
        order = telnyx.NumberOrder.create(
            phone_numbers=[{"phone_number": target_number}]
        )
        
        # 3. Associate with Voxa Telnyx Application
        telnyx_app_id = os.getenv("TELNYX_APP_ID")
        if telnyx_app_id:
            try:
                # Wait for order to propagate before querying ID
                time.sleep(3) 
                numbers = telnyx.PhoneNumber.list(filter={"phone_number": target_number})
                if getattr(numbers, 'data', None) and len(numbers.data) > 0:
                    number_id = numbers.data[0].id
                    telnyx.PhoneNumber.update(id=number_id, connection_id=telnyx_app_id)
            except Exception as e:
                print("Could not auto-bind connection_id. Number ordered though:", str(e))
                pass
                
        # 4. Save to Agent Settings in Supabase
        if supabase:
            supabase.table("agent_settings").update({
                "agent_phone_number": target_number
            }).eq("profile_id", req.profile_id).execute()
            
        return {"success": True, "phone_number": target_number}
        
    except telnyx.error.APIError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/webhooks/elevenlabs")
async def elevenlabs_webhook(request: Request):
    """
    Receives post-call webhooks from ElevenLabs.
    Logs the conversation transcript, duration, and deducts credits.
    """
    try:
        payload = await request.json()
        print("ElevenLabs Webhook Payload:", json.dumps(payload))
        
        # Check if conversation ended
        agent_id = payload.get("agent_id")
        conversation_id = payload.get("conversation_id")
        
        # In case the JSON structure wraps it in an event object
        if not agent_id and payload.get("event", {}).get("agent_id"):
            agent_id = payload["event"]["agent_id"]
            conversation_id = payload["event"]["conversation_id"]
            
        conversation = payload.get("conversation", {})
        if not conversation and payload.get("event", {}).get("conversation"):
            conversation = payload["event"]["conversation"]
            
        duration_secs = conversation.get("duration_secs", 0)
        transcript = conversation.get("transcript", [])
        recording_url = conversation.get("recording_url", "")
        
        if not agent_id or not conversation_id:
            return {"status": "ignored", "reason": "Missing agent/conversation ID"}
            
        if duration_secs == 0:
            return {"status": "ignored", "reason": "0 duration"}

        if not supabase:
            return {"status": "error", "reason": "Database missing"}

        # 1. Lookup Profile ID
        res = supabase.table("agent_settings").select("profile_id").eq("elevenlabs_agent_id", agent_id).execute()
        if not res.data:
            return {"status": "error", "reason": "Agent not found in database"}
            
        profile_id = res.data[0]["profile_id"]
        
        # 2. Calculate Cost (100 credits per minute = ~1.66 per sec)
        cost_credits = int(duration_secs * (100.0 / 60.0))
        
        # 3. Deduct Credits
        user_res = supabase.table("profiles").select("credits").eq("id", profile_id).execute()
        if user_res.data:
            current_credits = user_res.data[0].get("credits", 0)
            new_credits = max(0, current_credits - cost_credits)
            supabase.table("profiles").update({"credits": new_credits}).eq("id", profile_id).execute()
            
        # 4. Insert Call Log
        log_data = {
            "profile_id": profile_id,
            "agent_id": agent_id,
            "elevenlabs_call_id": conversation_id,
            "duration_seconds": duration_secs,
            "cost_credits": cost_credits,
            "transcript": transcript,
            "recording_url": recording_url
        }
        
        try:
            supabase.table("call_logs").insert(log_data).execute()
        except Exception as e:
            # Might fail if table doesn't exist yet, we can silently pass or log
            print("Failed to save call_log:", str(e))
            
        return {"status": "success", "credits_deducted": cost_credits}

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/webhooks/telnyx")
async def telnyx_webhook(request: Request):
    """
    Receives incoming call events from the Telnyx Call Control Application.
    Instantly bridges the call to ElevenLabs Conversational AI using SIP URI.
    """
    try:
        payload = await request.json()
        data = payload.get("data", {})
        event_type = data.get("event_type")
        
        if event_type == "call.initiated":
            call_control_id = data["payload"]["call_control_id"]
            to_number = data["payload"]["to"]
            
            # Lookup the ElevenLabs Agent ID configured for this phone number
            if not supabase:
                return {"status": "ok"}
                
            res = supabase.table("agent_settings").select("elevenlabs_agent_id").eq("agent_phone_number", to_number).execute()
            agent_id = None
            if len(res.data) > 0:
                agent_id = res.data[0].get("elevenlabs_agent_id")
            
            call = telnyx.Call()
            call.call_control_id = call_control_id
            
            if agent_id:
                print(f"Routing inbound call to SIP for agent {agent_id}")
                call.answer()
                call.transfer(to=f"sip:{agent_id}@sip.elevenlabs.io")
            else:
                print(f"No agent configured for {to_number}. Hanging up.")
                call.hangup()
                
    except Exception as e:
        print(f"Telnyx Webhook Error: {str(e)}")
        
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
