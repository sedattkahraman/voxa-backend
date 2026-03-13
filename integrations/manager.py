from typing import Dict, Any, Optional
from .cliniko import ClinikoIntegration
from .client_diary import ClientDiaryIntegration
from .gohighlevel import GoHighLevelIntegration
from .google import GoogleCalendarIntegration
from .outlook import OutlookCalendarIntegration

class IntegrationManager:
    """
    Routs AI voice agent requests (like "Check Calendar" or "Book Appointment") 
    to the correct backend implementation based on the user's Supabase settings.
    """

    @staticmethod
    def get_integration(provider: str, config: Dict[str, Any]):
        """
        Factory method to return the correctly initialized integration class.
        In a real scenario, this 'config' dict comes from the Supabase 
        `integrations` table for the user's profile_id.
        """
        if provider == "cliniko":
            return ClinikoIntegration(api_key=config.get("api_key"))
            
        elif provider == "client_diary":
            # Client Diary is Webhook/Zapier driven
            return ClientDiaryIntegration(webhook_url=config.get("webhook_url"))
            
        elif provider == "go_high_level":
            # GHL requires OAuth tokens
            access_token = config.get("access_token")
            location_id = config.get("location_id")
            return GoHighLevelIntegration(access_token, location_id)
            
        elif provider == "google_calendar":
            return GoogleCalendarIntegration(config.get("access_token"), config.get("refresh_token"))
            
        elif provider == "outlook":
            return OutlookCalendarIntegration(config.get("access_token"), config.get("refresh_token"))
            
        else:
            raise ValueError(f"Unknown integration provider: {provider}")

    # Example of how the Voice Agent (ElevenLabs/Vapi) would call this:
    # 
    # def check_availability(profile_id: str, date_from: str, date_to: str):
    #     user_integrations = supabase.table('integrations').select('*').eq('profile_id', profile_id).execute()
    #     for integration in user_integrations.data:
    #         if integration['status'] == 'connected':
    #             service = IntegrationManager.get_integration(integration['provider'], integration['config'])
    #             return service.get_available_slots(date_from, date_to)
