from fastapi import APIRouter, Request, HTTPException
import logging
import os
from dotenv import load_dotenv
from datetime import datetime
from app.database import get_db_cursor, commit_changes
from app.models import LeadData, ZohoLeadData
from app.zoho_integration import send_lead_to_zoho
import traceback
import sys
sys.stdout.reconfigure(encoding='utf-8')

env_path = r"D:\Sena Projects\test_aladdin_bot_cursor\.env"
load_dotenv(dotenv_path=env_path)
# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('google_leads.log')
    ]
)
logger = logging.getLogger(__name__)

# Create FastAPI router
google_router = APIRouter(prefix="/google", tags=["google_leads"])


# Save lead details to a backup text file
def save_to_text_file(lead_data: dict):
    try:
        base_dir = r"D:\Sena Projects\test_aladdin_bot_cursor\Google_leads_textfiles"
        os.makedirs(base_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"google_lead_{timestamp}.txt"
        filepath = os.path.join(base_dir, filename)
        with open(filepath, "w") as f:
            f.write(f"Lead Data - {timestamp}\n")
            f.write("=" * 50 + "\n")
            for key, value in lead_data.items():
                f.write(f"{key}: {value}\n")
            f.write("=" * 50 + "\n")
        logger.info(f"Lead data saved to {filepath}")
        return filepath
    except Exception as e:
        logger.error(f"Error saving to text file: {str(e)}")
        raise


# Handle Google SEO leads
@google_router.post("/google-seo-lead")
async def google_seo_lead(request: Request):
    return await process_landing_page_lead(request, source="Google SEO")

# Handle Google Ad landing page leads
@google_router.post("/google-ad-lead")
async def google_ad_lead(request: Request):
    return await process_landing_page_lead(request, source="Google Ad")

# Common logic to handle Google leads
async def process_landing_page_lead(request: Request, source: str):
    try:
        # Step 1: Parse incoming JSON
        lead_data = await request.json()
        logger.info(f"Received lead from {source}: {lead_data}")

        # Step 2: Ensure 'source' is included in the data
        lead_data_with_source = {**lead_data, "source": source}
        logger.info(f"Lead data with source added: {lead_data_with_source}")

        # Step 3: Validate using Pydantic model
        validated_data = LeadData(**lead_data_with_source)
        logger.info(f"Validated lead data: {validated_data.dict()}")

        # Step 4: Save to text file
        filename = save_to_text_file(validated_data.dict())

        # Step 5: Store to PostgreSQL
        conn, cur = get_db_cursor()
        try:
            cur.execute("""
                INSERT INTO leads (
                    name, email, whatsapp_number, travel_location,
                    travel_date, no_of_days, no_of_persons,
                    tour_type, source
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                validated_data.name,
                validated_data.email,
                validated_data.whatsapp,
                validated_data.travel_location,
                validated_data.travel_date,
                validated_data.no_of_days,
                validated_data.no_of_persons,
                validated_data.tour_type,
                validated_data.source
            ))
            lead_id = cur.fetchone()["id"]
            logger.info(f"Lead from {source} stored in DB with ID: {lead_id}")

            # Step 6: Push to Zoho CRM
            zoho_lead = ZohoLeadData(**validated_data.dict())
            zoho_response = await send_lead_to_zoho(zoho_lead)
            logger.info(f"Zoho CRM response for {source} lead: {zoho_response}")

            # Step 7: Return response
            return {
                "status": "success",
                "message": f"Lead from {source} processed successfully",
                "lead_id": lead_id,
                "text_file": filename,
                "zoho_response": zoho_response,
                "data": validated_data.dict()
            }

        except Exception as e:
            logger.error(f"Error processing {source} lead: {str(e)}")
            logger.error(traceback.format_exc())
            raise HTTPException(status_code=400, detail=f"Error: {str(e)}")

        finally:
            commit_changes(conn)

    except Exception as e:
        logger.error(f"Error in {source} lead processing: {str(e)}")
        logger.error(traceback.format_exc())  # ✅ Log full error trace
        raise HTTPException(status_code=400, detail=f"Error: {str(e)}")
