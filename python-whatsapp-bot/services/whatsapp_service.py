import logging
from fastapi import HTTPException

from utils.whatsapp_utils import parse_incoming
from services.conversation_flow import conv_flow# the singleton ConversationFlow

logger = logging.getLogger(__name__)


class WhatsAppService:
    @staticmethod
    async def verify_webhook(mode: str, token: str, challenge: str, verify_token_env: str) -> str:
        """Basic GET verification."""
        if mode == "subscribe" and token == verify_token_env and challenge:
            logger.info("✅  WEBHOOK_VERIFIED")
            return challenge
        raise HTTPException(status_code=403, detail="Verification failed")

    # ---- POST handler -----------------------------------------------------

    @staticmethod
    async def handle_webhook(body: dict) -> dict:
        """
        Receives *any* WhatsApp callback.  
        * Status / delivery events → 200 OK, no further action.  
        * Chat messages          → funnelled into conv_flow.handle_message().
        """
        is_chat, wa_id, profile_name, message = parse_incoming(body)

        # Non-chat event (status/delivery) → just ack
        if not is_chat:
            return {"status": "ok"}

        try:
            # Pass the full payload down; conv_flow will do deeper parsing
            await conv_flow.handle_event(body)
            return {"status": "ok"}

        except Exception as exc:  # noqa: BLE001
            logger.error(f"Error in WhatsAppService.handle_webhook: {exc}")
            raise HTTPException(status_code=500, detail="Internal server error") from exc
