import logging
from fastapi.responses import JSONResponse
import json
import httpx
from datetime import datetime
from openai import OpenAI
from asyncio import Lock

# Import configuration variables and prompts
from config.env import ACCESS_TOKEN, VERSION, PHONE_NUMBER_ID, OPENAI_API_KEY
from config.prompts import SYSTEM_PROMPT, USER_PROMPT
from config.activities import ACTIVITIES
from config.hotels import HOTELS
from config.state_template import get_destinations, get_budget_options
from utils.llm_Call import generate_llm_response 
from utils.transcribe import transcribe_audio_from_whatsapp

# Configure logging
logging.basicConfig(level=logging.INFO)

# Initialize in-memory sessions and lock
sessions = {}
sessions_lock = Lock()

# Initialize synchronous OpenAI client
client = OpenAI(api_key=OPENAI_API_KEY)

# --- Session Management ---
async def initialize_session(wa_id: str, profile_name: str):
    """Initialize a new session for a user."""
    async with sessions_lock:
        if wa_id not in sessions:
            sessions[wa_id] = {
                "conversation_history": [],
                "user_data": {"name": profile_name},
                "state": "greeting",  # Start with destination
                "destination": None,
                "num_guests": None,
                "selected_activities": [],
                "custom_activities": [],
                "preferred_hotels": [],
                "departure_city": None,
                "local_tips_requested": False,
                "departure_date": None,
                "return_date": None,
                "budget": None,
                "other_preferences": None,
                "last_activity": datetime.now().isoformat()
            }

async def update_session(wa_id: str, user_message: str = None, bot_response: str = None, **kwargs):
    """Update the session with a new message, state, and other data."""
    async with sessions_lock:
        if wa_id not in sessions:
            return
        if user_message:
            sessions[wa_id]["conversation_history"].append(f"User: {user_message}")
        if bot_response:
            sessions[wa_id]["conversation_history"].append(f"Bot: {bot_response}")
        sessions[wa_id]["last_activity"] = datetime.now().isoformat()
        sessions[wa_id].update(kwargs)  # Update state or other session data

# --- Message Validation ---
def is_valid_whatsapp_message(body: dict) -> tuple[bool, str, str, dict]:
    """
    Validate the WhatsApp webhook payload and extract wa_id, profile_name, and message.
    Returns (is_valid, wa_id, profile_name, message).
    """
    try:
        wa_id = body["entry"][0]["changes"][0]["value"]["contacts"][0]["wa_id"]
        profile_name = body["entry"][0]["changes"][0]["value"]["contacts"][0]["profile"]["name"]
        message = body["entry"][0]["changes"][0]["value"]["messages"][0]

        # Normalize voice message as audio type
        if message.get("type") == "voice":
            message["type"] = "audio"
            message["audio"] = message.get("voice")  # move 'voice' to 'audio'

    except (KeyError, IndexError):
        logging.error("Invalid payload structure: missing wa_id, profile.name, or message")
        return False, "", "", {}

    is_valid = (
        body.get("object")
        and body.get("entry")
        and body["entry"][0].get("changes")
        and body["entry"][0]["changes"][0].get("value")
        and body["entry"][0]["changes"][0]["value"].get("messages")
        and body["entry"][0]["changes"][0]["value"]["messages"][0]
    )
    return is_valid, wa_id, profile_name, message



# --- Sending Messages ---
async def send_text_message(wa_id: str, text: str):
    """Send a text message to the user via the WhatsApp API."""
    url = f"https://graph.facebook.com/{VERSION}/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Content-type": "application/json",
        "Authorization": f"Bearer {ACCESS_TOKEN}",
    }
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": wa_id,
        "type": "text",
        "text": {"preview_url": False, "body": text},
    }

    async with httpx.AsyncClient() as http_client:
        try:
            response = await http_client.post(url, data=json.dumps(payload), headers=headers, timeout=10)
            response.raise_for_status()
            logging.info(f"Text message sent to {wa_id}: Status {response.status_code}")
            return response.status_code
        except httpx.TimeoutException:
            logging.error(f"Timeout occurred while sending text message to {wa_id}")
            return JSONResponse(content={"status": "error", "message": "Request timed out"}, status_code=408)
        except httpx.HTTPStatusError as e:
            logging.error(f"Request failed for {wa_id}: {str(e)}")
            return JSONResponse(content={"status": "error", "message": "Failed to send message"}, status_code=500)

async def send_image_message(wa_id: str, image_url: str, caption: str):
    """Send an image message to the user via the WhatsApp API."""
    url = f"https://graph.facebook.com/{VERSION}/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Content-type": "application/json",
        "Authorization": f"Bearer {ACCESS_TOKEN}",
    }
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": wa_id,
        "type": "image",
        "image": {
            "link": image_url,
            "caption": caption
        }
    }

    async with httpx.AsyncClient() as http_client:
        try:
            response = await http_client.post(url, data=json.dumps(payload), headers=headers, timeout=10)
            response.raise_for_status()
            logging.info(f"Image message sent to {wa_id}: Status {response.status_code}")
            return response.status_code
        except httpx.TimeoutException:
            logging.error(f"Timeout occurred while sending image message to {wa_id}")
            return JSONResponse(content={"status": "error", "message": "Request timed out"}, status_code=408)
        except httpx.HTTPStatusError as e:
            logging.error(f"Request failed for {wa_id}: {str(e)}")
            return JSONResponse(content={"status": "error", "message": "Failed to send message"}, status_code=500)

async def send_video_message(wa_id: str, video_url: str, caption: str = ""):
    """Send a video message to the user via the WhatsApp API."""
    url = f"https://graph.facebook.com/{VERSION}/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Content-type": "application/json",
        "Authorization": f"Bearer {ACCESS_TOKEN}",
    }
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": wa_id,
        "type": "video",
        "video": {
            "link": video_url,
            "caption": caption
        }
    }

    async with httpx.AsyncClient() as http_client:
        try:
            response = await http_client.post(url, data=json.dumps(payload), headers=headers, timeout=10)
            response.raise_for_status()
            logging.info(f"Video message sent to {wa_id}: Status {response.status_code}")
            logging.info(f"Response JSON: {response.json()}")
            return response.status_code
        except httpx.TimeoutException:
            logging.error(f"Timeout occurred while sending video message to {wa_id}")
            return JSONResponse(content={"status": "error", "message": "Request timed out"}, status_code=408)
        except httpx.HTTPStatusError as e:
            logging.error(f"Request failed for {wa_id}: {str(e)}")
            return JSONResponse(content={"status": "error", "message": "Failed to send message"}, status_code=500)   

async def send_list_message(wa_id: str, header: str, body: str, options: list, action_button: str):
    """Send a list message to the user via the WhatsApp API."""
    url = f"https://graph.facebook.com/{VERSION}/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Content-type": "application/json",
        "Authorization": f"Bearer {ACCESS_TOKEN}",
    }
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": wa_id,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "header": {"type": "text", "text": header},
            "body": {"text": body},
            "action": {
                "button": action_button,
                "sections": [
                    {
                        "title": "Options",
                        "rows": [{"id": opt["id"], "title": opt["title"]} for opt in options]
                    }
                ]
            }
        }
    }

    async with httpx.AsyncClient() as http_client:
        try:
            response = await http_client.post(url, data=json.dumps(payload), headers=headers, timeout=10)
            response.raise_for_status()
            logging.info(f"List message sent to {wa_id}: Status {response.status_code}")
            return response.status_code
        except httpx.TimeoutException:
            logging.error(f"Timeout occurred while sending list message to {wa_id}")
            return JSONResponse(content={"status": "error", "message": "Request timed out"}, status_code=408)
        except httpx.HTTPStatusError as e:
            logging.error(f"Request failed for {wa_id}: {str(e)}")
            return JSONResponse(content={"status": "error", "message": "Failed to send message"}, status_code=500)

async def send_reply_buttons(wa_id: str, header: str, body: str, buttons: list):
    """Send a reply buttons message to the user via the WhatsApp API."""
    url = f"https://graph.facebook.com/{VERSION}/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Content-type": "application/json",
        "Authorization": f"Bearer {ACCESS_TOKEN}",
    }
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": wa_id,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "header": {"type": "text", "text": header},
            "body": {"text": body},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": btn["id"], "title": btn["title"]}} for btn in buttons
                ]
            }
        }
    }

    async with httpx.AsyncClient() as http_client:
        try:
            response = await http_client.post(url, data=json.dumps(payload), headers=headers, timeout=10)
            response.raise_for_status()
            logging.info(f"Reply buttons message sent to {wa_id}: Status {response.status_code}")
            return response.status_code
        except httpx.TimeoutException:
            logging.error(f"Timeout occurred while sending reply buttons message to {wa_id}")
            return JSONResponse(content={"status": "error", "message": "Request timed out"}, status_code=408)
        except httpx.HTTPStatusError as e:
            logging.error(f"Request failed for {wa_id}: {str(e)}")
            return JSONResponse(content={"status": "error", "message": "Failed to send message"}, status_code=500)


async def trigger_state(wa_id: str, message: dict = None):
    """Trigger interactive UI message based on the user's current state."""
    state = sessions[wa_id]["state"]
    user_name = sessions[wa_id]["user_data"]["name"].capitalize()
    destination = sessions[wa_id].get("destination", "your destination")

    if state == "greeting":
        await send_reply_buttons(
            wa_id,
            header="Welcome to Sena Holidays!",
            body=f"Hello {user_name}, I’m Lila, your travel assistant. \n\nI’m here to help you plan your dream vacation!",
            buttons=[{"id": "start", "title": "Let's start planning"}]
        )

    elif state == "destination":
        await send_list_message(
            wa_id,
            header="Choose Your Destination",
            body=f" Where would you like to go, {user_name}? \n\nSelect one of the options below, or just text me any other destination you have in mind and I’ll be happy to suggest some ideas!",
            options=get_destinations(),
            action_button="Select Destination"
        )

    elif state == "num_guests":
        await send_text_message(
            wa_id,
            "How many guests will be traveling, including yourself? (e.g., 4)"
        )

    elif state == "departure_date":
        await send_text_message(
            wa_id,
            "When would you like to depart? Please enter the date in YYYY-MM-DD format (e.g., 2025-06-15)."
        )

    elif state == "return_date":
        await send_text_message(
            wa_id,
            "When would you like to return? Please enter the date in YYYY-MM-DD format (e.g., 2025-06-25)."
        )

    elif state == "budget":
        await send_list_message(
            wa_id,
            header="Budget Range",
            body=f"Let’s talk about your budget for this trip to {destination}. What’s your preferred budget range in INR for the entire trip?",
            options=get_budget_options(),
            action_button="Select Budget"
        )

    elif state == "custom_budget":
        await send_text_message(
            wa_id,
            "No problem! What’s your total trip budget in INR? (e.g., 300000)"
        )

    elif state == "departure_city":
        await send_text_message(
            wa_id,
            f"To help with flights, where will you be flying from? (e.g., Mumbai, Delhi)"
        )

    elif state == "local_tips":
        await send_reply_buttons(
            wa_id,
            header="Local Tips",
            body=f"I’ve got some local tips for {destination}! Would you like to hear them?",
            buttons=[
                {"id": "yes_tips", "title": "Yes"},
                {"id": "no_tips", "title": "No"}
            ]
        )

    elif state == "summary":
        await send_reply_buttons(
            wa_id,
            header="Trip Summary",
            body="Would you like to refine the plan, connect with an agent, or start over?",
            buttons=[
                {"id": "refine_plan", "title": "Refine Plan"},
                {"id": "contact_agent", "title": "Contact Agent"},
                {"id": "start_over", "title": "Start Over"}
            ]
        )

    else:
        # await send_text_message(wa_id, "Let’s continue planning your trip step-by-step.")
        logging.warning(f"No trigger logic defined for state: {state}")


async def handle_text_with_llm(wa_id: str, message: dict):
    """Handle fallback text messages using LLM for any state."""
    message_body = message.get("text", {}).get("body", "")
    session = sessions[wa_id]
    response = await generate_llm_response(session, message_body)

    reply = response["reply"]
    next_state = response.get("next_state")
    updates = response.get("update", {})

    await update_session(wa_id, user_message=message_body, bot_response=reply, **updates)
    await send_text_message(wa_id, reply)

    if next_state:
        await update_session(wa_id, state=next_state)
        await trigger_state(wa_id)
# --- Core Message Processing ---
async def process_whatsapp_message(body: dict):
    """Process incoming WhatsApp messages and route based on user state."""
    try:
        is_valid, wa_id, profile_name, message = is_valid_whatsapp_message(body)
        if not is_valid:
            logging.error("Invalid WhatsApp message payload")
            return

        # Ensure session exists
        if wa_id not in sessions:
            await initialize_session(wa_id, profile_name)
            await trigger_state(wa_id)
            return

        state = sessions[wa_id].get("state", "")

        # Use LLM to handle ALL text messages
        if message["type"] == "text":
            await handle_text_with_llm(wa_id, message)
            return
        
        if message["type"] == "audio":
            media_id = message["audio"]["id"]
            transcript = await transcribe_audio_from_whatsapp(media_id)

            await update_session(wa_id, user_message=transcript)
            response = await generate_llm_response(sessions[wa_id], transcript)
            
            reply = response["reply"]
            next_state = response.get("next_state")
            updates = response.get("update", {})

            await update_session(wa_id, user_message=transcript, bot_response=reply, **updates)
            await send_text_message(wa_id, reply)

            if next_state:
                await update_session(wa_id, state=next_state)
                await trigger_state(wa_id)
            return

        # --- Handle Known Interactive Inputs ---
        if state == "greeting":
            if message["type"] == "interactive" and "button_reply" in message["interactive"]:
                button_id = message["interactive"]["button_reply"]["id"]
                if button_id == "start":
                    await update_session(wa_id, user_message=button_id, state="destination")
                    await trigger_state(wa_id)

        elif state == "destination":
            if message["type"] == "interactive" and "list_reply" in message["interactive"]:
                selected_destination = message["interactive"]["list_reply"]["title"]
                if selected_destination == "Other":
                    await update_session(wa_id, user_message=selected_destination, bot_response="I’d love to hear more! Where would you like to go?", state="destination_other")
                    await send_text_message(wa_id, "I’d love to hear more! Where would you like to go?")
                else:
                    await update_session(wa_id, user_message=selected_destination, bot_response=f"Great, we’re heading to {selected_destination}! How many guests will be traveling?", destination=selected_destination, state="num_guests")
                    await trigger_state(wa_id)

        elif state == "budget":
            if message["type"] == "interactive" and "list_reply" in message["interactive"]:
                selected_budget = message["interactive"]["list_reply"]["id"]
                if selected_budget == "custom_budget":
                    await update_session(wa_id, user_message="Custom budget", bot_response="No problem! What’s your budget in INR?", state="custom_budget")
                    await send_text_message(wa_id, "No problem! What’s your budget in INR?")
                else:
                    budget_title = message["interactive"]["list_reply"]["title"]
                    await update_session(wa_id, user_message=budget_title, bot_response="Thanks! Let’s continue.", budget=budget_title, state="summary")
                    await trigger_state(wa_id)

        elif state == "summary":
            if message["type"] == "interactive" and "button_reply" in message["interactive"]:
                choice = message["interactive"]["button_reply"]["id"]
                if choice == "refine_plan":
                    await update_session(wa_id, user_message="Refine Plan", bot_response="Sure! What would you like to change?")
                    await send_text_message(wa_id, "Sure! What would you like to change?")
                elif choice == "contact_agent":
                    await update_session(wa_id, user_message="Contact Agent", bot_response="I’ll connect you with a Sena Holidays agent shortly.")
                    await send_text_message(wa_id, "You’ll hear from us soon!")
                elif choice == "start_over":
                    await initialize_session(wa_id, profile_name)
                    await trigger_state(wa_id)

        else:
            await update_session(wa_id, user_message="Unknown input", bot_response="Let’s continue from where we left off.")
            await trigger_state(wa_id)

    except KeyError as e:
        logging.error(f"Missing key: {e}")
        await send_text_message(wa_id, "Looks like something broke. Resetting your session...")
        await initialize_session(wa_id, profile_name)
        await trigger_state(wa_id)

    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        await send_text_message(wa_id, "Oops! Something went wrong. Try again in a moment.")                