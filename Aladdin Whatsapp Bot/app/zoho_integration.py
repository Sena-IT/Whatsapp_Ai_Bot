import os
import logging
import requests
import httpx
from fastapi import HTTPException
from dotenv import load_dotenv
from app.models import ZohoLeadData
import sys
sys.stdout.reconfigure(encoding='utf-8')

# env_path = r"D:\Sena Projects\test_aladdin_bot_cursor\.env"
load_dotenv()
logger = logging.getLogger(__name__)

print("REFRESH TOKEN LOADED:888888888", os.getenv("ZOHO_REFRESH_TOKEN"))


def get_new_access_token():
    url = "https://accounts.zoho.in/oauth/v2/token"
    data = {
        "refresh_token": os.getenv("ZOHO_REFRESH_TOKEN"),
        "client_id": os.getenv("ZOHO_CRM_CLIENT_ID"),
        "client_secret": os.getenv("ZOHO_CRM_CLIENT_SECRET"),
        "grant_type": "refresh_token"
    }

    logging.info(f"🔍 Token request payload: {data}")

    response = requests.post(url, data=data)

    if response.status_code != 200:
        logging.error(f"❌ Token refresh failed: {response.text}")
        raise HTTPException(status_code=500, detail="Failed to refresh Zoho token")

    try:
        result = response.json()
    except Exception:
        logging.error(f"❌ Error parsing token response: {response.text}")
        raise HTTPException(status_code=500, detail="Zoho token response is not JSON")

    access_token = result.get("access_token")
    if not access_token:
        logging.error("❌ access_token missing in response!")
        raise HTTPException(status_code=500, detail="Could not retrieve Zoho access token")

    logging.info(f"✅ Zoho access token: {access_token}")
    return access_token



async def send_lead_to_zoho(lead: ZohoLeadData):
    access_token = get_new_access_token()
    if not access_token:
        raise HTTPException(status_code=500, detail="Could not retrieve Zoho access token")

    payload = {
        "data": [
            {
                "First_Name": lead.name.split(" ", 1)[0],
                "Last_Name": lead.name.split(" ", 1)[1] if len(lead.name.split(" ", 1)) > 1 else ".",
                "Company": "Aladdin Holidays",
                "Email": lead.email,
                "Phone": lead.whatsapp,
                "Lead_Source": lead.source or "Website Form",
                "Tour_Type": lead.tour_type,
                "Location": lead.travel_location,
                "Travels_Date": lead.travel_date,
                "Days": str(lead.no_of_days),
                "Persons": str(lead.no_of_persons)
            }
        ]
    }

    url = os.getenv("ZOHO_API_URL")
    if not url:
        raise HTTPException(status_code=500, detail="ZOHO_API_URL not configured")

    headers = {
        "Authorization": f"Zoho-oauthtoken {access_token}",
        "Content-Type": "application/json"
    }

    logger.info(f"📤 Sending lead to Zoho CRM: {payload}")

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0)) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            logger.info(f"✅ Zoho CRM Response: {response.json()}")
            return response.json()
    except httpx.HTTPStatusError as e:
        logger.error(f"❌ Zoho API error: {e.response.text}")
        raise HTTPException(status_code=e.response.status_code, detail=f"Zoho API error: {e.response.text}")
    except Exception as e:
        logger.error(f"❌ Failed to send lead to Zoho CRM: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
