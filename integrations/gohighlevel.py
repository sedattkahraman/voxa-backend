import requests
from typing import Dict, List
import datetime

class GoHighLevelIntegration:
    """
    GoHighLevel API V2 Integration.
    Requires OAuth 2.0. The tokens must be refreshed periodically.
    Docs reference: https://highlevel.stoplight.io/docs/integrations
    """

    BASE_URL = "https://services.leadconnectorhq.com"

    def __init__(self, access_token: str, location_id: str):
        self.access_token = access_token
        self.location_id = location_id
        self.headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Version": "2021-07-28",
            "Accept": "application/json"
        }

    def get_available_slots(self, date_from: str, date_to: str, calendar_id: str = None) -> List[Dict]:
        """
        Get free slots from a specific GHL Calendar (API V2).
        Returns a format that ElevenLabs LLM can read.
        """
        if not calendar_id:
            return []
            
        try:
            # Unix timestamp milliseconds
            import time
            from datetime import datetime
            
            # Simple conversion if YYYY-MM-DD
            if len(date_from) == 10:
                ts_from = int(datetime.strptime(date_from, "%Y-%m-%d").timestamp() * 1000)
                ts_to = int(datetime.strptime(date_to, "%Y-%m-%d").timestamp() * 1000)
            else:
                ts_from = int(time.time() * 1000)
                ts_to = ts_from + (86400 * 1000 * 7) # +7 days
                
            url = f"{self.BASE_URL}/calendars/{calendar_id}/free-slots?startDate={ts_from}&endDate={ts_to}"
            res = requests.get(url, headers=self.headers, timeout=10)
            
            if not res.ok:
                print(f"GHL Free Slots Error: {res.text}")
                return []
                
            # {"2021-07-28": {"slots": ["09:00 AM", "09:30 AM"]}}
            data = res.json()
            slots_out = []
            
            for date_key, day_data in data.items():
                if isinstance(day_data, dict) and 'slots' in day_data:
                    for slot in day_data['slots']:
                        slots_out.append({
                            "start": f"{date_key} {slot}",
                            "end": None,
                            "practitioner_id": calendar_id
                        })
            return slots_out
            
        except Exception as e:
            print(f"GHL Slot Fetch Error: {str(e)}")
            return []

    def book_appointment(self, calendar_id: str, contact_id: str, start_time: str) -> bool:
        """
        Create an appointment in GHL.
        If contact doesn't exist, use Contacts API to create them first.
        """
        # POST /calendars/events/appointments
        payload = {
            "calendarId": calendar_id,
            "locationId": self.location_id,
            "contactId": contact_id,
            "startTime": start_time,
            "title": "Voxa AI Appointment"
        }
        pass
    
    def create_or_update_contact(self, name: str, phone: str, email: str) -> str:
        """
        Returns Contact ID.
        """
        # POST /contacts/
        pass
