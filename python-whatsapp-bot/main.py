from fastapi import FastAPI
from config.env import validate_env
from api.routes import webhook_router


# Validate environment variables
validate_env()

import logging
logging.basicConfig(level=logging.INFO)
# Create FastAPI app
app = FastAPI()
@app.get("/")
async def root():
    return {"status": "ok"}

# Include webhook routes
app.include_router(webhook_router)