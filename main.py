import os
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from supabase import create_client, Client
import requests
import stripe
from fastapi.middleware.cors import CORSMiddleware

from integrations.manager import IntegrationManager
from integrations import stripe_helpers
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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
