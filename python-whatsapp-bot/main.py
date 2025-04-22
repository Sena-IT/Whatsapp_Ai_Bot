import logging
from fastapi import FastAPI, Request, Response, HTTPException, Depends
from fastapi.responses import JSONResponse
from app.config import load_configurations, configure_logging, Settings
from app.utils.whatsapp_utils import process_whatsapp_message, is_valid_whatsapp_message
from app.decorators.security import signature_required
from typing import Optional
import json

# Initialize FastAPI app
app = FastAPI(title="WhatsApp Bot API")

# Load configurations and configure logging
configure_logging()
settings = load_configurations()

print("SETTINGS",settings)

# @app.get("/webhook")
# async def verify_webhook(
#     hub_mode: str = None,
#     hub_verify_token: str = None,
#     hub_challenge: str = None
# ):
#     """Webhook verification endpoint for WhatsApp"""
#     if not all([hub_mode, hub_verify_token]):
#         raise HTTPException(
#             status_code=400,
#             detail="Missing parameters"
#         )
    
#     if hub_mode == "subscribe" and hub_verify_token == settings.VERIFY_TOKEN:
#         logging.info("WEBHOOK_VERIFIED")
#         return Response(content=hub_challenge)
#     else:
#         logging.info("VERIFICATION_FAILED")
#         raise HTTPException(
#             status_code=403,
#             detail="Verification failed"
#         )
    

@app.get("/sample-webhook")
async def verify_webhook(request: Request):
    """Webhook verification endpoint for WhatsApp"""
    params = request.query_params

    hub_mode = params.get("hub.mode")
    hub_verify_token = params.get("hub.verify_token")
    hub_challenge = params.get("hub.challenge")

    if not hub_mode or not hub_verify_token or not hub_challenge:
        logging.error("🚨 Missing parameters in webhook verification request")
        raise HTTPException(status_code=400, detail="Missing parameters")

    if hub_mode == "subscribe" and hub_verify_token == settings.VERIFY_TOKEN:
        print("**************",hub_verify_token)
        logging.info("✅ WEBHOOK_VERIFIED")
        return Response(content=hub_challenge, media_type="text/plain")
    else:
        logging.error("❌ VERIFICATION_FAILED: Invalid token")
        raise HTTPException(status_code=403, detail="Verification failed")




@app.post("/sample-webhook")
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

    # Check if it's a WhatsApp status update
    if (body.get("entry", [{}])[0]
        .get("changes", [{}])[0]
        .get("value", {})
        .get("statuses")):
        logging.info("Received a WhatsApp status update.")
        print("--------status body---------", body)
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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=True) 