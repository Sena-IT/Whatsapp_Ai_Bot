import logging
import hashlib
import hmac
from fastapi import Request, HTTPException, Depends
from app.config import load_configurations

settings = load_configurations()

def validate_signature(payload: str, signature: str) -> bool:
    """
    Validate the incoming payload's signature against our expected signature
    """
    # Use the App Secret to hash the payload
    expected_signature = hmac.new(
        bytes(settings.APP_SECRET, "latin-1"),
        msg=payload.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()

    # Check if the signature matches
    return hmac.compare_digest(expected_signature, signature)

async def signature_required(request: Request) -> bool:
    """
    FastAPI dependency to verify the WhatsApp webhook signature
    """
    signature = request.headers.get("X-Hub-Signature-256", "")[7:]  # Removing 'sha256='
    body = await request.body()
    
    if not validate_signature(body.decode("utf-8"), signature):
        logging.info("Signature verification failed!")
        raise HTTPException(
            status_code=403,
            detail="Invalid signature"
        )
    
    return True
