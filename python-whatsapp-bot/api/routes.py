import json
import logging
from schema.decorators.security import signature_required
from fastapi import APIRouter, Request, Response, HTTPException, Depends
from services.whatsapp_service import WhatsAppService

logger = logging.getLogger(__name__)

webhook_router = APIRouter()


@webhook_router.get("/sentos-webhook")
async def verify_webhook(request: Request):
    """Webhook verification endpoint for WhatsApp"""
    params = request.query_params

    hub_mode = params.get("hub.mode")
    hub_verify_token = params.get("hub.verify_token")
    hub_challenge = params.get("hub.challenge")

    challenge = await WhatsAppService.verify_webhook(hub_mode, hub_verify_token, hub_challenge)
    return Response(content=challenge, media_type="text/plain")




@webhook_router.post("/sentos-webhook")
async def webhook_handler(
    request: Request,
    verified: bool = Depends(signature_required)
):
    """Handle incoming webhook events from the WhatsApp API"""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        logging.error("Failed to decode JSON")
        raise HTTPException(
            status_code=400,
            detail="Invalid JSON provided"
        )

    return await WhatsAppService.handle_webhook(body)
