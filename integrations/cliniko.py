import requests
import datetime
from typing import List, Dict, Optional

class ClinikoIntegration:
    """
    Cliniko REST API Integration.
    Docs reference: https://github.com/redguava/cliniko-api
    """
    
    BASE_URL = "https://api.cliniko.com/v1"

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.headers = {
            "Accept": "application/json",
            "User-Agent": "Voxa_Agent (support@voxaai.com)"
        }
    
    def get_available_slots(self, date_from: str, date_to: str) -> List[Dict]:
        """
        Fetch available appointment times from Cliniko.
        date_from and date_to should be ISO strings (e.g., 2026-03-14)
        """
        try:
            response = requests.get(
                f"{self.BASE_URL}/available_times?from={date_from}&to={date_to}",
                auth=(self.api_key, ''),
                headers=self.headers,
                timeout=10
            )
            if not response.ok:
                print(f"Cliniko API Error: {response.status_code} - {response.text}")
                return []
                
            data = response.json()
            available_times = data.get("available_times", [])
            
            # Format nicely for the LLM to read
            slots = []
            for slot in available_times:
                slots.append({
                    "start": slot.get("appointment_start"),
                    "end": slot.get("appointment_end"),
                    "practitioner_id": slot.get("practitioner", {}).get("links", {}).get("self")
                })
            return slots
        except Exception as e:
            print(f"Failed to fetch Cliniko slots: {str(e)}")
            return []

    def book_appointment(self, patient_data: Dict, time_slot: str, appointment_type_id: str) -> bool:
        """
        Book an appointment. Requires retrieving or creating the Patient first.
        """
        # 1. Create Patient -> POST /v1/patients
        # 2. Create Appointment -> POST /v1/appointments
        pass

    def cancel_appointment(self, appointment_id: str) -> bool:
        """
        Cancel an existing appointment.
        """
        pass
