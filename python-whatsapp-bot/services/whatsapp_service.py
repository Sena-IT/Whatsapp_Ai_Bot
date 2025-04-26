import json
import logging
from fastapi import HTTPException
from utils.whatsapp_utils import process_whatsapp_message, is_valid_whatsapp_message
from config.env import VERIFY_TOKEN

logger = logging.getLogger(__name__)

class WhatsAppService:
    @staticmethod
    async def verify_webhook(hub_mode: str, hub_verify_token: str, hub_challenge: str) -> str:
        """Verify the WhatsApp webhook"""
        if not hub_mode or not hub_verify_token or not hub_challenge:
            logging.error("🚨 Missing parameters in webhook verification request")
            raise HTTPException(status_code=400, detail="Missing parameters")

        if hub_mode == "subscribe" and hub_verify_token == VERIFY_TOKEN:
            logging.info("✅ WEBHOOK_VERIFIED")
            return hub_challenge
        else:
            logging.error("❌ VERIFICATION_FAILED: Invalid token")
            raise HTTPException(status_code=403, detail="Verification failed")

    @staticmethod
    async def handle_webhook(body: dict) -> dict:
        """Handle incoming webhook events from the WhatsApp API"""
        # Check if it's a WhatsApp status update
        if (body.get("entry", [{}])[0]
            .get("changes", [{}])[0]
            .get("value", {})
            .get("statuses")):
            logging.info("Received a WhatsApp status update.")
            return {"status": "ok"}

        try:
            if is_valid_whatsapp_message(body):
                process_whatsapp_message(body)
                return {"status": "ok"}
            else:
                raise HTTPException(
                    status_code=404,
                    detail="Not a WhatsApp API event"
                )
        except Exception as e:
            logging.error(f"Error processing message: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail="Internal server error"
            ) 