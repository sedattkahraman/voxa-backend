import os
import stripe
from fastapi import HTTPException

# Determine if we are in test mode from environment
# Default to True for safety during development
STRIPE_TEST_MODE = os.getenv("STRIPE_TEST_MODE", "true").lower() == "true"

# Use test keys if in test mode, otherwise default to live keys
if STRIPE_TEST_MODE:
    stripe.api_key = os.getenv("STRIPE_TEST_SECRET_KEY", "sk_test_mock_key_for_development")
else:
    stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

def create_checkout_session(profile_id: str, email: str, plan_id: str, success_url: str, cancel_url: str):
    """
    Creates a Stripe Checkout Session for buying credits.
    Maps our internal plan_id to a specific price and credit amount.
    """
    # Define our plans and their raw Stripe prices (in cents) and credit output
    # In a real app, these price_ids would come from your Stripe Dashboard Products
    # But for a quick SaaS MVP without predefined products, we can use `price_data` for custom ad-hoc pricing
    plans = {
        "basic": {"amount": 4900, "credits": 500, "name": "Basic Package"},
        "standard": {"amount": 12900, "credits": 1500, "name": "Standard Package"},
        "premium": {"amount": 39900, "credits": 5000, "name": "Premium Package"},
        "enterprise": {"amount": 99900, "credits": 15000, "name": "Enterprise Package"}
    }

    if plan_id not in plans:
        raise HTTPException(status_code=400, detail="Invalid plan selected.")
    
    plan = plans[plan_id]

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            customer_email=email if email else None,
            line_items=[
                {
                    "price_data": {
                        "currency": "usd",
                        "product_data": {
                            "name": plan["name"],
                            "description": f"Adds {plan['credits']} AI Voice Minutes to your account.",
                        },
                        "unit_amount": plan["amount"],
                    },
                    "quantity": 1,
                }
            ],
            mode="payment",
            success_url=success_url,
            cancel_url=cancel_url,
            client_reference_id=profile_id, # Very important: Ties the payment back to the Supabase User
            metadata={
                "credits_to_add": plan["credits"],
                "plan_id": plan_id
            }
        )
        return {"sessionId": session.id, "url": session.url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
