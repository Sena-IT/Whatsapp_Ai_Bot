import json
import logging
from fastapi import APIRouter, Request, Response, Depends
from services.whatsapp_service import WhatsAppService
from schema.decorators.security import signature_required
from config.env import VERIFY_TOKEN

logger = logging.getLogger(__name__)

webhook_router = APIRouter()


@webhook_router.get("/sentos-webhook")
async def verify_webhook(request: Request):
    params = request.query_params
    challenge = await WhatsAppService.verify_webhook(
        params.get("hub.mode"),
        params.get("hub.verify_token"),
        params.get("hub.challenge"),
        VERIFY_TOKEN,
    )
    return Response(content=challenge, media_type="text/plain")


@webhook_router.post("/sentos-webhook")
async def webhook_handler(request: Request, _: bool = Depends(signature_required)):
    try:
        body = await request.json()
    except Exception:
        # non-JSON payload (e.g. Meta “ping” call) – just acknowledge
        return {"status": "ignored"}

    try:
        return await WhatsAppService.handle_webhook(body)
    except Exception as exc:
        # log the problem but still return 200 so Meta stops retrying
        logger.error(f"Webhook processing error: {exc}")
        return {"status": "error_logged"}
