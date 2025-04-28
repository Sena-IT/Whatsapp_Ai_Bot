# from fastapi import APIRouter, Request, HTTPException
# import logging
# import os
# import requests
# from dotenv import load_dotenv
# from app.database import get_db_cursor, commit_changes

# env_path = r"D:\Sena Projects\test_aladdin_bot_cursor\.env"
# load_dotenv(dotenv_path=env_path)

# logger = logging.getLogger(__name__)
# PAGE_ACCESS_TOKEN = os.getenv("GRAPH_API_ACCESS_TOKEN")

# facebook_router = APIRouter()

# # @facebook_router.post("/fbwebhook")
# # async def test(req: Request):
# #     print("req",req)

# # @facebook_router.post("/fbwebhook")
# # async def handle_fb_lead_event(request: Request):
# #     try:
# #         body = await request.json()
# #         logger.info(f"📩 Received FB Payload: {body}")

# #         for entry in body.get("entry", []):
# #             for change in entry.get("changes", []):
# #                 if change.get("field") == "leadgen":
# #                     lead_id = change["value"].get("leadgen_id")
# #                     logger.info(f"🔍 Fetching lead_id: {lead_id}")
# #                     lead_data = get_lead_data_from_facebook(lead_id)

# #                     if not lead_data:
# #                         logger.warning("⚠️ No lead data returned.")
# #                         continue

# #                     conn, cur = get_db_cursor()
# #                     cur.execute("""
# #                         INSERT INTO leads (
# #                             name, email, whatsapp_number, travel_location,
# #                             travel_date, no_of_days, no_of_persons,
# #                             tour_type, source
# #                         ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
# #                     """, (
# #                         lead_data.get("name"),
# #                         lead_data.get("email"),
# #                         lead_data.get("whatsapp"),
# #                         lead_data.get("travel_location"),
# #                         lead_data.get("travel_date"),
# #                         int(lead_data.get("no_of_days", 0)),
# #                         int(lead_data.get("no_of_persons", 0)),
# #                         lead_data.get("tour_type"),
# #                         "Facebook Lead Ad"
# #                     ))
# #                     commit_changes(conn)
# #                     logger.info("✅ Lead inserted into DB.")
# #         return {"status": "success"}
# #     except Exception as e:
# #         logger.error(f"❌ Error processing FB lead: {str(e)}", exc_info=True)
# #         raise HTTPException(status_code=500, detail=str(e))

# def get_lead_data_from_facebook(lead_id: str) -> dict:
#     try:
#         if not PAGE_ACCESS_TOKEN:
#             raise Exception("PAGE_ACCESS_TOKEN is missing.")

#         url = f"https://graph.facebook.com/v19.0/{lead_id}?access_token={PAGE_ACCESS_TOKEN}"
#         response = requests.get(url)
#         response.raise_for_status()

#         data = response.json()
#         field_data = data.get("field_data", [])
#         result = {field["name"]: field["values"][0] for field in field_data if field["values"]}

#         return {
#             "name": result.get("full_name", ""),
#             "email": result.get("email", ""),
#             "whatsapp": result.get("phone_number", ""),
#             "travel_location": result.get("travel_location", ""),
#             "travel_date": result.get("date_of_travel/month", ""),
#             "no_of_days": result.get("no_of_days", "0"),
#             "no_of_persons": result.get("no_of_persons", "0"),
#             "tour_type": result.get("tour_type", ""),
#             "departure_city": result.get("departure_city", "")
#         }
#     except Exception as e:
#         logging.error(f"❌ Failed to fetch Facebook lead data: {str(e)}", exc_info=True)
#         return {}

# # In your facebook_lead.py file
# @facebook_router.get("/fetch-lead/{lead_id}")
# async def fetch_lead_by_id(lead_id: str):
#     try:
#         logging.info(f"🔍 Fetching Facebook lead for ID: {lead_id}")
#         lead_data = get_lead_data_from_facebook(lead_id)

#         if not lead_data:
#             raise HTTPException(status_code=404, detail="No data found or fetch failed")

#         return {"status": "success", "lead_data": lead_data}
#     except Exception as e:
#         logging.error(f"❌ Error fetching lead {lead_id}: {str(e)}", exc_info=True)
#         raise HTTPException(status_code=500, detail=f"Exception: {str(e)}")