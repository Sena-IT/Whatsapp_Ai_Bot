from fastapi import FastAPI, Request, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import logging
import os
import json
import httpx
from app.database import execute_query, get_db_cursor, commit_changes
from app.routers.google_leads import google_router
#from app.routers.facebook_lead import facebook_router
from app.health import health_router
from app.models import FacebookLead
import sys
sys.stdout.reconfigure(encoding='utf-8')
from fastapi.responses import PlainTextResponse

env_path = r"D:\Sena Projects\test_aladdin_bot_cursor\.env"
load_dotenv(dotenv_path=env_path)

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
PAGE_ACCESS_TOKEN = os.getenv("CLIENT_GRAPH_API_ACCESS_TOKEN")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("app.log")
    ]
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Aladdin Holidays API", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

@app.on_event("startup")
async def startup_event():
    execute_query("""
        CREATE TABLE IF NOT EXISTS leads (
            id SERIAL PRIMARY KEY,
            name VARCHAR(255),
            email VARCHAR(255),
            whatsapp_number VARCHAR(20),
            travel_location VARCHAR(255),
            travel_date VARCHAR(50),
            no_of_days INTEGER,
            no_of_persons INTEGER,
            tour_type VARCHAR(50),
            source VARCHAR(50),
            created_at Timestamp DEFAULT CURRENT_TIMESTAMP,
            updated_at Timestamp DEFAULT CURRENT_TIMESTAMP
        )
    """)

 
# @app.api_route("/webhook-fb-test",methods=["GET", "POST"], response_class=PlainTextResponse)
# async def verify_webhook(request: Request):
#     if request.method == "GET":
#         mode = request.query_params.get("hub.mode")
#         token = request.query_params.get("hub.verify_token")
#         challenge = request.query_params.get("hub.challenge")
#         if mode == "subscribe" and token == VERIFY_TOKEN:
#             logger.info("Webhook verified.")
#             return Response(content=challenge, media_type="text/plain")
#         logger.warning("Invalid token during webhook verification.")
#         raise HTTPException(status_code=403, detail="Verification failed")
#     else:
#         data = await request.json()
#         print("Message received:", data.get("Message"))
#         return PlainTextResponse("Webhook POST received", status_code=200)

from fastapi.responses import JSONResponse

@app.api_route("/webhook-aladdin", methods=["GET", "POST"], response_class=PlainTextResponse)
async def verify_webhook(request: Request):
    if request.method == "GET":
        mode = request.query_params.get("hub.mode")
        token = request.query_params.get("hub.verify_token")
        challenge = request.query_params.get("hub.challenge")
        if mode == "subscribe" and token == VERIFY_TOKEN:
            print("✅ Webhook verified")
            return challenge
        raise HTTPException(status_code=403, detail="Verification failed")

    # POST handling
    try:
        payload = await request.json()
        print("📩 Incoming POST from Meta:", json.dumps(payload, indent=2))
        return JSONResponse({"status": "received"})
    except Exception as e:
        print(f"❌ Error parsing POST: {e}")
        raise HTTPException(status_code=400, detail="Invalid payload")




# @app.get("/fbb-webhook", response_class=PlainTextResponse)
# async def verify_webhook(request: Request):
#     params = dict(request.query_params)
#     if params.get("hub.verify_token") == VERIFY_TOKEN:
#         return params.get("hub.challenge")
#     return "Invalid verify token"

# @app.post("/fbb-webhook")
# async def capture_lead(request: Request):
#     data = await request.json()
#     print("📩 FB Payload:", json.dumps(data, indent=2))

#     try:
#         lead_id = data["entry"][0]["changes"][0]["value"]["leadgen_id"]
#         print(f"✅ Captured Lead ID: {lead_id}")

#         # Fetch lead details from Facebook
#         lead_url = f"https://graph.facebook.com/v19.0/{lead_id}?access_token={PAGE_ACCESS_TOKEN}"
#         async with httpx.AsyncClient() as client:
#             response = await client.get(lead_url)
#             lead_data = response.json()

#         print("📥 Full Lead Data:", json.dumps(lead_data, indent=2))

#         # Save to JSON file
#         lead_path = r'D:\Sena Projects\test_aladdin_bot_cursor\leads_json'
#         with open(lead_path, "w") as f:
#             json.dump(lead_data, f, indent=2)

#         return {"status": "lead captured", "lead_id": lead_id}
    
#     except Exception as e:
#         print(f"❌ Error: {e}")
#         return {"error": "Failed to process lead"}

app.include_router(google_router)
app.include_router(health_router)
# app.include_router(facebook_router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=True)