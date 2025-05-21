"""
WhatsApp payload helpers
------------------------
• parse_incoming()   → returns (is_chat, wa_id, profile_name, raw_msg)
• extract_message_details() → returns (is_chat, wa_id, profile_name, payload)
   payload = { "type": "...", "text": "...", "meta": {...} }
• transcribe_audio_from_whatsapp() proxy to utils.transcribe
"""

from __future__ import annotations
import httpx
import logging
from typing import Tuple, Dict, Any, Optional

import requests
from config.env import FACEBOOK_API_BASE, PHONE_NUMBER_ID, ACCESS_TOKEN


logger = logging.getLogger(__name__)


def is_valid_payload(body: dict) -> bool:
    """
    Legacy shim – just returns the `is_chat` boolean from parse_incoming().
    """
    return parse_incoming(body)[0]

def parse_incoming(body: Dict[str, Any]) -> Tuple[bool, Optional[str], Optional[str], Dict]:
    """
    Return (is_chat, wa_id, profile_name, raw_message_dict).

    • is_chat == False for delivery / read / typing / malformed callbacks.
    • raw_message_dict is the single 'messages[0]' object (may be empty {}) .
    """
    try:
        entry = body.get("entry")
        if not entry:
            return False, None, None, {}

        change = entry[0].get("changes", [])[0]
        value = change.get("value", {})

        # ---- skip non-chat callbacks ------------------------------------
        if value.get("statuses"):
            return False, None, None, {}

        messages = value.get("messages")
        contacts = value.get("contacts")
        if not (messages and contacts):
            return False, None, None, {}

        msg = messages[0]
        contact = contacts[0]

        if msg.get("from") == PHONE_NUMBER_ID:
            return False, None, None, {}

        wa_id = contact.get("wa_id")
        profile_name = contact.get("profile", {}).get("name")

        # Normalise voice ⇒ audio
        if msg.get("type") == "voice":
            msg["type"] = "audio"
            msg["audio"] = msg.pop("voice", {})

        return True, wa_id, profile_name, msg

    except Exception:
        # any weird schema => quietly treat as non-chat
        return False, None, None, {}


# -------------------------------------------------------------------------
# 2) High-level extractor for ConversationFlow
# -------------------------------------------------------------------------
def extract_message_details(
    body: Dict[str, Any]
) -> Tuple[bool, Optional[str], Optional[str], Dict[str, Any]]:
    """
    Convenience wrapper:

        (is_chat, wa_id, profile_name, payload_dict)

    payload_dict schema:
        {
            "type": "text" | "audio" | "interactive" | "unknown",
            "text": "user visible text or transcription",
            "meta": { arbitrary extra, e.g. audio_id, raw_interactive }
        }
    """
    is_chat, wa_id, profile_name, msg = parse_incoming(body)
    if not is_chat:
        return False, None, None, {}

    m_type = msg.get("type", "unknown")
    meta: Dict[str, Any] = {}

    if m_type == "text":
        text = msg["text"]["body"]

    elif m_type == "audio":
        audio_id = (msg.get("audio") or {}).get("id")
        meta["audio_id"] = audio_id
        text = ""  # will be filled after transcription

    elif m_type == "interactive":
        itm = msg["interactive"]
        if itm.get("type") == "button_reply":
            text = itm["button_reply"]["title"]
            meta["interactive"] = itm
            meta["button_id"] = itm["button_reply"]["id"]
        elif itm.get("type") == "list_reply":
            text = itm["list_reply"]["title"]
            meta["interactive"] = itm
            meta["button_id"] = itm["list_reply"]["id"]
        else:
            text = "(interactive)"
            meta["interactive"] = itm

    else:
        text = "(unsupported)"
        m_type = "unknown"

    meta["message_id"] = msg.get("id")
    payload = {"type": m_type, "text": text, "meta": meta}
    return True, wa_id, profile_name, payload


# -------------------------------------------------------------------------
# 3) Audio transcription proxy
# -------------------------------------------------------------------------
async def transcribe_audio_from_whatsapp(audio_id: str) -> str:
    """
    Thin proxy to utils.transcribe.transcribe_audio_from_whatsapp().
    Returns empty string on failure.
    """
    if not audio_id:
        return ""

    try:
        from utils.transcribe import transcribe_audio_from_whatsapp as _trans
        return await _trans(audio_id)
    except Exception as exc:  # noqa: BLE001
        logger.error(f"STT error for audio_id={audio_id}: {exc}")
        return ""

async def upload_audio_to_meta_cloud(audio_path):
    """Upload audio file to Meta's cloud storage"""
    print("-------------- Uploading audio to Meta cloud ----------------")

    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}"
    }
    
    url = f"{FACEBOOK_API_BASE}/{PHONE_NUMBER_ID}/media"

    with open(audio_path, 'rb') as file:
        files = {
            'file': ('audio.mp3', file, 'audio/mpeg')
        }
        
        payload = {
            'messaging_product': 'whatsapp',
            'type': 'audio'
        }    

        response = requests.post(url, files=files, data=payload, headers=headers)
        # uploaded_time = datetime.now()

        if response.status_code == 200:
            media_id = response.json()['id']
            logging.info("Audio uploaded successfully. Media ID: %s", media_id)
            return media_id
        else:
            logging.error("Failed to upload audio: %s", response.text)
            return None


async def upload_file_to_meta_cloud(file_path: str, content_type: str) -> Optional[str]:
    """Upload a file to Meta's cloud storage and return its media ID."""
    logger.info(f"Uploading {content_type} file to Meta cloud from path: {file_path}")

    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}"
    }
    
    url = f"{FACEBOOK_API_BASE}/{PHONE_NUMBER_ID}/media"
    
    import os # Import os for path.basename
    file_name = os.path.basename(file_path)

    with open(file_path, 'rb') as file:
        files = {
            'file': (file_name, file, content_type)  # Use provided content_type and extract filename
        }
        
        payload = {
            'messaging_product': 'whatsapp',
            'type': content_type # Make type dynamic based on content_type for broader use, or set to 'document' if only for docs
        }    

        try:
            async with httpx.AsyncClient() as client: # Use httpx for async request
                response = await client.post(url, files=files, data=payload, headers=headers)
            
            if response.status_code == 200:
                media_id = response.json().get('id')
                if media_id:
                    logger.info(f"File uploaded successfully. Media ID: {media_id}")
                    return media_id
                else:
                    logger.error(f"Media ID not found in response: {response.text}")
                    return None
            else:
                logger.error(f"Failed to upload file: {response.status_code} - {response.text}")
                return None
        except httpx.RequestError as e:
            logger.error(f"HTTP request failed: {e}")
            return None
        except Exception as e: # Catch any other exceptions
            logger.error(f"An unexpected error occurred during file upload: {e}")
            return None


async def delete_uploaded_file(media_id):

        print("------------------- delete_uploaded_file ------------------------")

        url = f"{FACEBOOK_API_BASE}/{PHONE_NUMBER_ID}/{media_id}"
        headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}"
        }
        response = requests.delete(url, headers=headers)
        

        if response.status_code == 200 :
            print(f"--------------------- File{media_id} deleted from Meta Server.------------------------")
        else:
            print(f"-----------------------Failed to delete{media_id} file.----------------------------")           
        