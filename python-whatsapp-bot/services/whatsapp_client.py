import httpx
from typing import List, Dict

import requests
from config.env import FACEBOOK_API_BASE, PHONE_NUMBER_ID, ACCESS_TOKEN
import logging

logger = logging.getLogger(__name__)

class WhatsAppClient:
    """Encapsulates WhatsApp API interactions."""
    def __init__(self, api_base: str, phone_id: str, token: str):
        self.api_base = api_base
        self.phone_id = phone_id
        self.headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    async def send_text(self, wa_id: str, body: str):
        url = f"{self.api_base}/{self.phone_id}/messages"
        payload = {"messaging_product":"whatsapp","recipient_type":"individual","to":wa_id,
                   "type":"text","text":{"body":body}}
        async with httpx.AsyncClient() as client:
            await client.post(url, json=payload, headers=self.headers, timeout=10)

    async def send_list(self, wa_id: str, header: str, body: str, options: List[Dict], button: str):
        url = f"{self.api_base}/{self.phone_id}/messages"
        payload = {
            "messaging_product":"whatsapp","recipient_type":"individual","to":wa_id,
            "type":"interactive","interactive":{
                "type":"list",
                "header":{"type":"text","text":header},
                "body":{"text":body},
                "action":{
                    "button":button,
                    "sections":[{"title":"Options","rows":[
                        {"id":opt['id'],"title":opt['title']} for opt in options
                    ]}]
                }
            }
        }
        async with httpx.AsyncClient() as client:
            await client.post(url, json=payload, headers=self.headers, timeout=10)

    async def send_image(self, wa_id: str, image_url: str, caption: str = None):
        url = f"{self.api_base}/{self.phone_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": wa_id,
            "type": "image",
            "image": {"link": image_url, **({"caption": caption} if caption else {})}
        }
        async with httpx.AsyncClient() as client:
            await client.post(url, json=payload, headers=self.headers, timeout=10)

    async def send_video(self, wa_id: str, video_url: str, caption: str = None):
        url = f"{self.api_base}/{self.phone_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": wa_id,
            "type": "video",
            "video": {"link": video_url, **({"caption": caption} if caption else {})}
        }
        async with httpx.AsyncClient() as client:
            await client.post(url, json=payload, headers=self.headers, timeout=10)

    async def send_voice(self, wa_id: str, audio_url: str):
        url = f"{self.api_base}/{self.phone_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": wa_id,
            "type": "audio",
            "audio": {"link": audio_url}
        }
        async with httpx.AsyncClient() as client:
            await client.post(url, json=payload, headers=self.headers, timeout=10)

    async def send_reply_buttons(self, wa_id: str, header: str, body: str, buttons: List[Dict]):
        url = f"{self.api_base}/{self.phone_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": wa_id,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "header": {"type": "text", "text": header},
                "body": {"text": body},
                "action": {"buttons": [{"type": "reply", "reply": {"id": btn['id'], "title": btn['title']}} for btn in buttons]}
            }
        }
        async with httpx.AsyncClient() as client:
            await client.post(url, json=payload, headers=self.headers, timeout=10)        

    async def send_audio(self, wa_id: str, media_id: str):
        
        try:
            url = f"{self.api_base}/{self.phone_id}/messages"
            payload = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": wa_id,
                "type": "audio",
                "audio": {
                    "id": media_id
                }
            }
            response = requests.post(
                url, json=payload, headers=self.headers, timeout=10
            )

            response_data = response.json()
            
            # Check for WhatsApp API specific errors
            if 'error' in response_data:
                error = response_data['error']
                logging.error(f"WhatsApp API Error: {error.get('message', 'Unknown error')}")
                logging.error(f"Error Code: {error.get('code')}")
                logging.error(f"Error Details: {error.get('details', 'No details')}")
                return error.get('code', 500)
                
            # Check for successful response
            if response.status_code == 200 and 'messages' in response_data:
                logging.info(f"Message sent successfully. Message ID: {response_data['messages'][0]['id']}")
                return 200
            else:
                logging.error(f"Unexpected response: {response_data}")
                return 500
                
        except requests.Timeout:
            logging.error("Timeout occurred while sending message")
            return 408


    


whatsapp_client = WhatsAppClient(api_base=FACEBOOK_API_BASE, phone_id=PHONE_NUMBER_ID, token=ACCESS_TOKEN)            