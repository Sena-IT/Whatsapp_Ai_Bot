"""
Central coordinator: WhatsApp event → LLM → reply.
Now supports GREETING → REQUIREMENT → PLANNING with live backend data.
"""

import asyncio
import logging
import os
from typing import Dict, Any, List
import datetime
import locale
try:
    locale.setlocale(locale.LC_ALL, 'en_IN.utf8')
except locale.Error:
    locale.setlocale(locale.LC_ALL, "C.UTF-8")

from services.session_service import session_svc
from services.whatsapp_client import whatsapp_client
from services.llm_orchestrator import llm, tts
from services import backend_client

from utils.whatsapp_utils import extract_message_details, transcribe_audio_from_whatsapp, upload_audio_to_meta_cloud, delete_uploaded_file

logger = logging.getLogger(__name__)


REQ_KEYS = ["destination_city", "travellers", "departure_city",
            "budget_inr", "start_date", "end_date"]


def _complete(req: dict) -> bool:
    return all(req.get(k) for k in REQ_KEYS)

def _should_show_sheet(session: dict, updated: dict) -> bool:
    """
    Show the requirement sheet only when:
      • we are still in REQUIREMENT, and
      • at least one field was updated in this turn
    """
    return session["state"] == "REQUIREMENT" and bool(updated)


# Helper function for date formatting (can be outside the class or a static method)
def format_display_date(date_str):
    if not date_str or date_str == ' ':
        return ' '
    try:
        dt_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d")
        day = dt_obj.day
        # Simplified suffix logic for brevity, can be expanded
        if 11 <= day <= 13:
            suffix = "th"
        else:
            suffixes = {1: "st", 2: "nd", 3: "rd"}
            suffix = suffixes.get(day % 10, "th")
        return dt_obj.strftime(f"%B {day}{suffix}, %Y") 
    except ValueError:
        logger.warning(f"Could not format date: {date_str}")
        return date_str # Fallback

# Helper function for budget formatting
def format_budget(amount_inr):
    if amount_inr is None or amount_inr == ' ':
        return ' '
    try:
        amount = float(amount_inr)
        # Format with commas for thousands, ensure it handles integers correctly
        formatted_amount = f"{amount:,.0f}" if amount == int(amount) else f"{amount:,.2f}"
        return f"₹{formatted_amount}/-"
    except (ValueError, TypeError):
        logger.warning(f"Could not format budget: {amount_inr}")
        return str(amount_inr) # Fallback


class ConversationFlow:
    

    async def handle_event(self, body: Dict[str, Any]) -> None:
        ok, wa_id, profile_name, payload = extract_message_details(body)
        if not ok:
            return
        
        await self._process(wa_id, profile_name, payload)

    # =================== MAIN STATE MACHINE ========================= #
    async def _process(self, wa_id: str, profile_name: str, payload: Dict[str, Any]):
        s = session_svc.get(wa_id)

        # ---- new visitor ------------------------------------------- #
        if not s:
            await session_svc.init_session(wa_id, profile_name)
            await whatsapp_client.send_reply_buttons(
                wa_id,
                header="Welcome to Sena Holidays!",
                body=f"Hello {profile_name.capitalize()}! I'm Sena, your friendly travel planning assistant. 😊\n" \
                     f"You can chat with me using text or by sending voice notes!\n\n" \
                     f"For planning your trip:\n" \
                     f"✨ Plan Here: We can figure out your travel needs right here in our WhatsApp chat.\n" \
                     f"📝 Itinerary Builder: For a more detailed, line-by-line plan, head over to our Itinerary Builder.\n\n" \
                     f"How would you like to begin?",
                buttons=[
                    {"id": "start_planning_here", "title": "✨ Plan in Whatsapp"},
                    {"id": "goto_itinerary_builder", "title": "📝 Itinerary Builder"}
                ],
            )
            return

        # ---- duplicate WA delivery? -------------------------------- #
        if payload.get("meta", {}).get("message_id") == s.get("last_msg_id"):
            return
        s["last_msg_id"] = payload.get("meta", {}).get("message_id") # Storing last_msg_id in session

        msg_type = payload["type"]
        msg_text = payload["text"]
        meta = payload.get("meta", {})

        if s["state"] == "PLANNING":
            await _planning_loop(wa_id, s, msg_type, msg_text, meta)
            return
    
        # ---- GREETING → REQUIREMENT trigger ------------------------ #
        if s["state"] == "GREETING":
            if msg_type == "interactive" and meta.get("button_id") == "start_planning_here":
                await session_svc.set_state(wa_id, "REQUIREMENT")
                await whatsapp_client.send_text(
                    wa_id,
                    "Awesome – I'd love to help you plan your trip! "
                    "Let's figure out the details below. 😊",
                )
                await whatsapp_client.send_text(wa_id, _sheet(s))
            elif msg_type == "interactive" and meta.get("button_id") == "goto_itinerary_builder":
                await whatsapp_client.send_text(
                    wa_id,
                    "You can access our Itinerary Builder here: [Link to Itinerary Builder - Coming Soon!]"
                )
                # User remains in GREETING state, they can click "Start Planning Here" next or send another message.
            return

        # ---- REQUIREMENT interactive destination pick -------------- #
        if s["state"] == "REQUIREMENT" and msg_type == "interactive":
            list_id = meta.get("list_id") or meta.get("button_id")
            if list_id and list_id.startswith("dest_"):
                city = list_id.split("_", 1)[1].title()
                await session_svc.update_requirements(wa_id, {"destination_city": city})
                s = session_svc.get(wa_id) # Refresh session
                await whatsapp_client.send_text(wa_id, f"Great choice – {city} it is! 🛫")
                if _should_show_sheet(s, {"destination_city": city}):
                    await whatsapp_client.send_text(wa_id, _sheet(s))
                return

        # ---- voice → text ------------------------------------------ #
        if msg_type == "audio":
            tr = await transcribe_audio_from_whatsapp(meta["audio_id"])
            if tr:
                msg_text = tr
            else:
                await whatsapp_client.send_text(wa_id, "Sorry, didn't catch that. Please type 🙂")
                return

        # ---- LLM call --------------------------------------------- #
        resp = await llm.generate_response(s, msg_text) 
        logger.info("LLM result: %s", resp)

        llm_update_payload = resp.get("update")

        if llm_update_payload:
            # === Pre-process for date ranges if LLM sends them in one field ===
            raw_start_date_str = llm_update_payload.get("start_date")
            raw_end_date_str = llm_update_payload.get("end_date")

            if isinstance(raw_start_date_str, str):
                normalized_raw_start_date = raw_start_date_str.lower()
                delimiter = None
                if " to " in normalized_raw_start_date:
                    delimiter = " to "
                elif " - " in normalized_raw_start_date: # check for " - " as well
                    delimiter = " - "
                
                if delimiter:
                    parts = normalized_raw_start_date.split(delimiter, 1) # Split only on the first occurrence
                    if len(parts) == 2:
                        potential_start = parts[0].strip()
                        potential_end = parts[1].strip()

                        # If potential_end is just a day number (e.g., from "july 3 to 7"), try to prefix month from potential_start
                        if potential_end.isdigit():
                            month_prefix_from_start = ""
                            if ' ' in potential_start: # e.g. "july 3"
                                first_digit_index = -1
                                for i_char, char_val in enumerate(potential_start):
                                    if char_val.isdigit():
                                        first_digit_index = i_char
                                        break
                                if first_digit_index > 0:
                                    month_prefix_from_start = potential_start[:first_digit_index].strip() # "july"
                            
                            if month_prefix_from_start: # If we got a month like "july"
                                potential_end = f"{month_prefix_from_start} {potential_end}" # "july 7"
                        
                        llm_update_payload["start_date"] = potential_start
                        # Only update end_date if it was missing or contained the same full range string
                        if not raw_end_date_str or raw_end_date_str == raw_start_date_str:
                            llm_update_payload["end_date"] = potential_end
                            logger.info(f"Split date range '{raw_start_date_str}' into start='{llm_update_payload['start_date']}', end='{llm_update_payload['end_date']}'")
                        else:
                            logger.info(f"Used start from range '{raw_start_date_str}' as '{llm_update_payload['start_date']}', end_date '{raw_end_date_str}' was already distinct or preferred.")

            # === Attempt to reformat dates from LLM (Workaround) ===
            for date_field in ["start_date", "end_date"]:
                if date_field in llm_update_payload and isinstance(llm_update_payload[date_field], str):
                    original_date_str = llm_update_payload[date_field]
                    # Remove ordinal suffixes (st, nd, rd, th)
                    cleaned_date_str = original_date_str.lower() \
                        .replace("st", "").replace("nd", "").replace("rd", "").replace("th", "")
                    
                    parsed_date = None
                    # Define common date formats LLM might output textually
                    # Adding year is important if LLM omits it.
                    possible_formats = [
                        "%B %d, %Y", "%B %d %Y",  # Month Day, Year / Month Day Year
                        "%b %d, %Y", "%b %d %Y",    # Mon Day, Year / Mon Day Year
                        "%B %d", "%b %d",          # Month Day (assume current year)
                        "%d %B %Y", "%d %b %Y",    # Day Month Year
                        "%d %B", "%d %b"           # Day Month (assume current year)
                    ]
                    current_year = datetime.datetime.now().year

                    for fmt in possible_formats:
                        try:
                            parsed_date = datetime.datetime.strptime(cleaned_date_str, fmt)
                            if parsed_date.year == 1900: # Default year from strptime if not in format
                                parsed_date = parsed_date.replace(year=current_year)
                            llm_update_payload[date_field] = parsed_date.strftime("%Y-%m-%d")
                            logger.info(f"Reformatted LLM date for {date_field} from '{original_date_str}' to '{llm_update_payload[date_field]}'")
                            break # Found a working format
                        except ValueError:
                            continue # Try next format
                    if not parsed_date:
                        logger.warning(f"Could not parse/reformat date string '{original_date_str}' from LLM for {date_field}. Sending as is.")
            # === End Date Reformatting ===

            # === Budget Calculation Logic (from previous step, ensure it uses potentially updated num_travellers) ===
            current_travellers_for_budget = s["requirements"].get("travellers", [])
            if "travellers" in llm_update_payload: # If LLM is updating travellers in this same payload
                current_travellers_for_budget = llm_update_payload["travellers"]
            num_travellers = len(current_travellers_for_budget) if current_travellers_for_budget else 0
            
            if "budget_inr" in llm_update_payload and llm_update_payload["budget_inr"] is not None:
                llm_budget_val_str = str(llm_update_payload["budget_inr"])
                final_budget_val = None
                try:
                    llm_budget_numerical_val = float(llm_budget_val_str) # Initial budget from LLM
                except ValueError:
                    logger.warning(f"Could not convert LLM budget '{llm_budget_val_str}' to float initially. Skipping budget modification.")
                    llm_budget_numerical_val = None

                if llm_budget_numerical_val is not None:
                    is_per_head_explicitly_flagged = llm_update_payload.get("budget_per_head") is True
                    is_per_head_in_text = False
                    original_numerical_budget_from_text = None # Value like 20000.0

                    if msg_text:
                        if ("per head" in msg_text.lower() or \
                            "each" in msg_text.lower() or \
                            "per person" in msg_text.lower()):
                            is_per_head_in_text = True
                            
                            import re
                            # Regex to find a number (possibly with decimal, possibly with 'k') before "per head", "each", "per person"
                            # e.g., "20k per head", "20000 per person", "20.5k per head", "20 per head"
                            match = re.search(r"(\d+(?:\.\d+)?k?)\s*(?:per head|each|per person)", msg_text.lower())
                            if match:
                                val_str = match.group(1)
                                try:
                                    if 'k' in val_str:
                                        original_numerical_budget_from_text = float(val_str.replace('k', '')) * 1000.0
                                    else:
                                        original_numerical_budget_from_text = float(val_str)
                                    logger.info(f"Extracted per-head budget from text: {original_numerical_budget_from_text}")
                                except ValueError:
                                    logger.warning(f"Could not convert extracted budget string '{val_str}' to float.")

                    if num_travellers > 0:
                        if is_per_head_explicitly_flagged: 
                            # Case 1: LLM says budget_inr is per_head (e.g. {budget_inr: 20000, budget_per_head: true})
                            final_budget_val = llm_budget_numerical_val * num_travellers
                            logger.info(f"Budget calc: LLM flagged per_head. Using LLM budget {llm_budget_numerical_val} * {num_travellers} = {final_budget_val}")
                        
                        elif is_per_head_in_text: 
                            # Case 2: "per head" in user text, LLM did NOT explicitly flagged budget_per_head
                            if original_numerical_budget_from_text is not None: 
                                # Subcase 2a: We extracted a value (e.g. 20000 from "20k per head") from text
                                final_budget_val = original_numerical_budget_from_text * num_travellers
                                logger.info(f"Budget calc: 'per head' in text. Using extracted text budget {original_numerical_budget_from_text} * {num_travellers} = {final_budget_val}")
                            else: 
                                # Subcase 2b: "per head" in text, but couldn't extract value from text.
                                # LLM's budget_inr is ambiguous. It might be per-head, or LLM might have already multiplied it.
                                # Safest assumption: LLM already calculated total if it saw "per head" and didn't flag budget_per_head=true
                                final_budget_val = llm_budget_numerical_val # Use LLM's value as is (e.g. 60000)
                                logger.warning(f"Budget calc: 'per head' in text, no value extracted from text. LLM budget_inr ('{llm_budget_numerical_val}') is ambiguous. Assuming it as total: {final_budget_val}")
                        else: 
                            # Case 3: No indication of "per head" from LLM flag or text
                            final_budget_val = llm_budget_numerical_val
                            logger.info(f"Budget calc: No 'per head'. Using LLM budget as total: {final_budget_val}")
                    else: 
                        # No (positive number of) travellers, use budget as is without multiplication
                        final_budget_val = llm_budget_numerical_val
                        logger.info(f"Budget calc: No/Zero travellers ({num_travellers}). Using LLM budget as is: {final_budget_val}")

                    if final_budget_val is not None:
                        llm_update_payload["budget_inr"] = final_budget_val
                    
                    if "budget_per_head" in llm_update_payload: # Clean up flag in all cases
                        del llm_update_payload["budget_per_head"]
            # === End Budget Calculation Logic ===
            
            # Handle null ages from LLM - convert to a default or remove if backend doesn't like null
            if "travellers" in llm_update_payload:
                for traveller in llm_update_payload["travellers"]:
                    if traveller.get("age") is None:
                        # Option 1: Remove age if backend allows optional age
                        # del traveller["age"]
                        # Option 2: Set a placeholder if backend requires age but allows a special value (e.g., 0, -1)
                        # For now, let's assume backend might prefer if age field is omitted if unknown, or change null to 0
                        # This depends on backend schema. Forcing to 0 if null for now to avoid sending null.
                        traveller["age"] = 0 # Or handle as per backend requirement
                        logger.info(f"Replaced null age with 0 for traveller {traveller.get('name')}")

            await session_svc.update_requirements(wa_id, llm_update_payload)
            s = session_svc.get(wa_id) 
            if _should_show_sheet(s, llm_update_payload):
                await whatsapp_client.send_text(wa_id, _sheet(s))

        # ---- auto flip to PLANNING (Request 3) --------------------------------- #
        if s["state"] == "REQUIREMENT" and _complete(s["requirements"]):
            await session_svc.set_state(wa_id, "PLANNING")
            # Assuming session_svc.set_planning_step is a method that updates a 'planning_step' field in the session
            await session_svc.update_session_field(wa_id, "planning_step", "activities") 
            await session_svc.update_session_field(wa_id, "activities_shown", False) # Reset flag for new planning session
            s = session_svc.get(wa_id) # Refresh session

            await whatsapp_client.send_text(
                wa_id,
                "✅ All set! Let's start by picking some fun activities for your trip." # New message for Request 3
            )
            # Trigger _planning_loop to show initial activities
            await _planning_loop(wa_id, s, msg_type="", text="", meta={"trigger": "initial_activities"})
            return  

        # ---- still in REQUIREMENT: maybe send suggestions ---------- #
        if (
            s["state"] == "REQUIREMENT"
            and not s["requirements"]["destination_city"]
            and not s.get("suggestions_shown") # Check if suggestions already shown
        ):
            await session_svc.update_session_field(wa_id, "suggestions_shown", True) # Mark as shown
            s = session_svc.get(wa_id) # Refresh session
            await _send_destinations_bundle(wa_id)
            return # Return to avoid falling through to default reply after sending bundle

        # ---- default reply from LLM (if not handled by other flows) --- #
        if resp.get("reply"): # Ensure there is a reply from LLM
            if msg_type == "audio": # Handle audio reply if TTS is intended
                audio_path = await tts.generate_audio(resp["reply"])
                if audio_path:
                    media_id = await upload_audio_to_meta_cloud(audio_path)
                    if media_id:
                        response_code = await whatsapp_client.send_audio(wa_id, media_id)
                        if os.path.exists(audio_path): os.remove(audio_path)
                        if response_code == 200: await delete_uploaded_file(media_id)
                    else: # Fallback to text if audio upload fails
                        await whatsapp_client.send_text(wa_id, resp["reply"])
                else: # Fallback to text if TTS fails
                    await whatsapp_client.send_text(wa_id, resp["reply"])
            
            # Log history only if a reply was sent
            s["history"].extend([f"User: {msg_text}", f"Bot: {resp['reply']}"])
            # Consider calling session_svc.save_session(s) or similar if history needs explicit save
        return # Explicit return after handling a message in REQUIREMENT state or GREETING


def _travellers_block(trav_list):
    primary_user_name = None
    if trav_list and trav_list[0].get("is_primary"): # Assuming LLM might flag primary user
        primary_user_name = trav_list[0]["name"].capitalize()

    if not trav_list:
        return "*2. Travellers (count, ages):* " 
    
    num_travellers = len(trav_list)
    traveller_details = []
    
    # Use primary user's name if available and it's the first in list
    # Otherwise, default to "Traveller X" naming for subsequent travellers.
    # This is still heuristic and depends on LLM output structure.
    
    first_traveller_name = primary_user_name # Use a cap for this from user's own name
    
    for i, t in enumerate(trav_list):
        name = t.get("name", f"Traveller {i + 1}")
        age_str = f" ({t['age']})" if t.get("age") else ""

        if i == 0 and first_traveller_name: # If it's the first traveller and we have a primary user name
             # Check if LLM provided name is generic or if it's the primary user's name already
            if name.lower().startswith("person") or name.lower().startswith("child") or name.lower() == first_traveller_name.lower():
                 display_name = first_traveller_name # Use capitalized primary name
            else: # LLM provided a specific different name for the first person
                 display_name = name.capitalize()
        elif name.lower().startswith("person ") or name.lower().startswith("child "):
            display_name = f"Traveller {i + 1}" # Standardize generic names
        else:
            display_name = name.capitalize() # Capitalize other specific names

        traveller_details.append(f"{display_name}{age_str}")
        
    return f"*2. Travellers ({num_travellers}):* {', '.join(traveller_details)}"



def _sheet(session: dict) -> str:
    r = session["requirements"]
    trav = _travellers_block(r["travellers"]) # _travellers_block already formats its label as "*2. Travellers...*"
    budget_display = r['budget_inr']
    if isinstance(budget_display, (int, float)):
        budget_display = int(budget_display)
    
    customer_name_display = r['customer_name']
    if customer_name_display:
        customer_name_display = customer_name_display.capitalize()

    # Your existing _travellers_block modification already includes "2. Travellers (count, ages): "
    # We need to ensure _travellers_block itself makes its label part bold if it's not already.
    # For other lines, we make the label part bold here.

    budget_display_formatted = format_budget(r.get('budget_inr'))
    start_date_formatted = format_display_date(r.get('start_date'))
    end_date_formatted = format_display_date(r.get('end_date'))

    return "\n".join([
        "*📝 TRAVEL REQUIREMENT SHEET*", 
        "",
        f"*1. Name:* {customer_name_display or ' '}",  # Bold label
        trav, # Assumes _travellers_block handles its own bolding for "2. Travellers..."
        f"*3. Departure City:* {r['departure_city'] or ' '}", # Bold label
        f"*4. Destination City:* {r['destination_city'] or ' '}", # Bold label
        f"*5. Tentative Total Budget:* {budget_display_formatted or ' '}",  # Bold label
        f"*6. Start date:* {start_date_formatted or ' '}", # Bold label
        f"*7. End date:* {end_date_formatted or ' '}", # Bold label
        "",
        "_You can answer in any order – I'll tick them off as we go!_",
    ])


async def _send_destinations_bundle(wa_id: str):
    # three images + list as before (reuse your existing helper)
    
    # images …
    await whatsapp_client.send_image(
        wa_id,
        "https://cdn.pixabay.com/photo/2017/08/30/11/12/singapore-2696704_1280.jpg",
        "Singapore 🇸🇬 – gardens, theme parks, spotless streets\nhttps://www.youtube.com/watch?v=kij3n1iikKc&ab_channel=VisitSingapore\n",
    )
    await whatsapp_client.send_image(
        wa_id,
        "https://cdn.pixabay.com/photo/2016/08/08/16/09/indonesia-1578647_1280.jpg",
        "Bali 🇮🇩 – temples, surf and sunsets\nhttps://www.youtube.com/watch?v=LCqK7wZd2Pk&ab_channel=TheLuxurySignature",
    )
    await whatsapp_client.send_image(
        wa_id,
        "https://cdn.pixabay.com/photo/2016/02/28/20/23/dubai-1227538_1280.jpg",
        "Dubai 🇦🇪 – malls, desert safaris and sky-high views\nhttps://www.youtube.com/watch?v=fuSpjxrdhTw&ab_channel=VisitDubai",
    )
    await asyncio.sleep(1)
    await whatsapp_client.send_list(
        wa_id,
        header="Pick a destination",
        body="Tap to add to your plan:",
        options=[
            {"id": "dest_singapore", "title": "Singapore"},
            {"id": "dest_bali", "title": "Bali"},
            {"id": "dest_dubai", "title": "Dubai"},
        ],
        button="Show places",
    )


async def _planning_loop(wa_id: str, session: dict, msg_type: str, text: str, meta: dict):
    step = session.get("planning_step") or "ask"
    plan = session.get("plan", {}) 
    if not plan:
        plan = {
            "activity_ids": [], "activities": [], 
            "hotel_ids": [], "hotel": None, 
            "flight_ids": [], "flight": None, 
            "total_price_inr": 0
        }
        session["plan"] = plan

    dest = session["requirements"]["destination_city"]
    logger.info(f"Planning loop: wa_id={wa_id}, step={step}, msg_type={msg_type}, text='{text}', meta={meta}")

    # ---------- initial ask (now bypassed by Request 3 if coming from requirements completion) --- #
    if step == "ask" and meta.get("trigger") != "initial_activities": 
        await whatsapp_client.send_list(
            wa_id,
            header="What shall we plan first?",
            body="Pick one of these to continue:",
            options=[
                {"id": "plan_activities", "title": "Activities"},
                {"id": "plan_hotels",     "title": "Hotels"},
                {"id": "plan_flights",    "title": "Flights"},
            ],
            button="Choose Option"
        )
        return

    # ---------- Activities (Client-side Pagination) ---------- #
    if step == "activities":
        city = session["requirements"]["destination_city"]
        page_size = 7

        # Fetch and store all activities if not already in session for this city/planning round
        if not session.get("all_city_activities") or session.get("current_activity_city") != city:
            all_activities_for_city = await backend_client.get_activities(city)
            logger.info(f"Fetched activities from backend for city '{city}': {all_activities_for_city}")
            logger.info(f"Number of activities fetched for city '{city}': {len(all_activities_for_city)}")
            await session_svc.update_session_field(wa_id, "all_city_activities", all_activities_for_city)
            await session_svc.update_session_field(wa_id, "current_activity_city", city)
            await session_svc.update_session_field(wa_id, "activity_page", 1)
            session["all_city_activities"] = all_activities_for_city # Update local session copy
            session["current_activity_city"] = city
            session["activity_page"] = 1
        
        all_activities = session.get("all_city_activities", [])
        print(f"all_activities: {all_activities}")
        current_page = session.get("activity_page", 1)

        if meta.get("trigger") == "initial_activities" or not session.get("activities_shown_this_page"):
            start_index = (current_page - 1) * page_size
            end_index = start_index + page_size
            activities_to_show = all_activities[start_index:end_index]

            if activities_to_show:
                await _show_activities(wa_id, activities_to_show)
                await session_svc.update_session_field(wa_id, "activities_shown_this_page", True)
                session["activities_shown_this_page"] = True
                await whatsapp_client.send_text(wa_id, "Type 'more' for more options, or 'done' when finished.")
            elif current_page == 1: # No activities at all for the city
                await whatsapp_client.send_text(wa_id, f"Sorry, I couldn't find any activities for {city} right now.")
                await session_svc.update_session_field(wa_id, "planning_step", "hotels")
                await session_svc.update_session_field(wa_id, "all_city_hotels", None) # Reset for hotels
                await session_svc.update_session_field(wa_id, "current_hotel_city", None)
                s_refreshed = session_svc.get(wa_id)
                await _planning_loop(wa_id, s_refreshed, msg_type="", text="", meta={"trigger": "initial_hotels"})
            else: # No more activities on subsequent pages
                await whatsapp_client.send_text(wa_id, "No more activities to show.")
            return

        elif msg_type == "text":
            user_input = text.strip().lower()
            # current_options are implicitly defined by what _show_activities displayed and stored in last_shown_activities_map

            if user_input == "done":
                await whatsapp_client.send_text(wa_id, "Great! Activities selection complete.")
                await session_svc.update_session_field(wa_id, "planning_step", "hotels")
                await session_svc.update_session_field(wa_id, "all_city_hotels", None) # Reset for hotels logic
                await session_svc.update_session_field(wa_id, "current_hotel_city", None)
                s_refreshed = session_svc.get(wa_id)
                await _planning_loop(wa_id, s_refreshed, msg_type="", text="", meta={"trigger": "initial_hotels"})
                return
            
            elif user_input == "more":
                next_page = current_page + 1
                start_index = (next_page - 1) * page_size
                
                if start_index < len(all_activities):
                    await session_svc.update_session_field(wa_id, "activity_page", next_page)
                    session["activity_page"] = next_page # Update local session
                    await session_svc.update_session_field(wa_id, "activities_shown_this_page", False) # Trigger display of next page
                    s_refreshed = session_svc.get(wa_id)
                    # Call _planning_loop again to re-enter and display the new page
                    await _planning_loop(wa_id, s_refreshed, msg_type="", text="", meta={"trigger": "initial_activities"}) 
                else:
                    await whatsapp_client.send_text(wa_id, "No more activities to show.")
                return

            else: # Try to parse numbers for selection (Keep existing selection logic)
                selected_indices = []
                # Simple parsing for "1", "1,2", "1 and 2"
                parts = user_input.replace("and", ",").split(',')
                for part in parts:
                    part = part.strip()
                    if part.isdigit():
                        selected_indices.append(int(part) - 1) # 0-indexed

                added_activities_names = []
                if selected_indices and current_options:
                    for index in selected_indices:
                        if 0 <= index < len(current_options):
                            selected_opt = current_options[index] # This is like {'id': 'act_xyz', 'title': '1. Activity Name'}
                            activity_id = selected_opt['id']
                            # We need the full activity details, not just what was in current_options for display
                            # This implies _show_activities or the calling code needs to store full details of shown items
                            # Or, we fetch activity details by ID here. For now, assume we can get name.
                            # Let's assume current_options stored by _show_activities has enough info or an ID to fetch.
                            
                            # Find the full activity detail from a list of all fetched_activities if stored, or by ID
                            # This part is tricky without knowing what exactly `current_activity_options` contains
                            # For now, let's assume we can get a name for the confirmation message.
                            # The actual object to add to plan["activities"] should be the full dict.
                            
                            # Conceptual: find full activity object.
                            # For demo, let's say we just use the title for now.
                            activity_name_from_title = selected_opt['title'].split('.', 1)[-1].strip() if '.' in selected_opt['title'] else selected_opt['title']

                            # To properly add to plan, we need the original activity object.
                            # _show_activities should store a mapping or the full objects keyed by their display number.
                            # Let's modify session store for this: session["last_shown_activities_map"] = {1: activity_obj1, 2: activity_obj2}
                            
                            last_shown_map = session.get("last_shown_activities_map", {})
                            activity_to_add = last_shown_map.get(index + 1) # 1-indexed key

                            if activity_to_add:
                                if activity_to_add not in plan.get("activities", []): # Avoid duplicates
                                    plan.setdefault("activities", []).append(activity_to_add)
                                    plan.setdefault("activity_ids", []).append(activity_to_add["id"])
                                    added_activities_names.append(activity_to_add.get("name", activity_name_from_title))
                                else:
                                    added_activities_names.append(f"{activity_to_add.get('name', activity_name_from_title)} (already added)")

                    if added_activities_names:
                        await whatsapp_client.send_text(wa_id, f"Added: {', '.join(added_activities_names)}. Select more, type 'more', or 'done'.")
                    else:
                        await whatsapp_client.send_text(wa_id, "Couldn't match your selection. Please use the numbers shown, or type 'more' or 'done'.")
                else:
                    await whatsapp_client.send_text(wa_id, "Sorry, I didn't understand that. Please select by number (e.g., 1, 2), or type 'more' or 'done'.")
                return
        # Fallback if not text or other conditions for activities step
        return

    # ---------- Hotels (Potentially Client-side Pagination - applying similar pattern) ---------- #
    elif step == "hotels":
        city = session["requirements"]["destination_city"]
        hotel_page_size = 2 # Example page size for hotels

        if not session.get("all_city_hotels") or session.get("current_hotel_city") != city:
            all_hotels_for_city = await backend_client.get_hotels(city)
            await session_svc.update_session_field(wa_id, "all_city_hotels", all_hotels_for_city)
            await session_svc.update_session_field(wa_id, "current_hotel_city", city)
            await session_svc.update_session_field(wa_id, "hotel_page", 1)
            session["all_city_hotels"] = all_hotels_for_city
            session["current_hotel_city"] = city
            session["hotel_page"] = 1
        
        all_hotels = session.get("all_city_hotels", [])
        current_hotel_page = session.get("hotel_page", 1)

        if meta.get("trigger") == "initial_hotels" or not session.get("hotels_shown_this_page"):
            start_index = (current_hotel_page - 1) * hotel_page_size
            end_index = start_index + hotel_page_size
            hotels_to_show = all_hotels[start_index:end_index]

            if hotels_to_show:
                await _show_hotels(wa_id, hotels_to_show)
                await session_svc.update_session_field(wa_id, "hotels_shown_this_page", True)
                session["hotels_shown_this_page"] = True
                await whatsapp_client.send_text(wa_id, "Please select a hotel by its number. Type 'more' for more options, or 'skip'/'done' if not interested.")
            elif current_hotel_page == 1:
                await whatsapp_client.send_text(wa_id, f"Sorry, I couldn't find any hotels for {city} right now.")
                await session_svc.update_session_field(wa_id, "planning_step", "flights")
                s_refreshed = session_svc.get(wa_id)
                await _planning_loop(wa_id, s_refreshed, msg_type="", text="", meta={"trigger": "initial_flights"})
            else:
                await whatsapp_client.send_text(wa_id, "No more hotels to show.")
            return
        
        elif msg_type == "text":
            user_input = text.strip().lower()

            if user_input in ["done", "skip", "none"]:
                await whatsapp_client.send_text(wa_id, "Okay, moving on to flights.")
                await session_svc.update_session_field(wa_id, "planning_step", "flights")
                s_refreshed = session_svc.get(wa_id)
                await _planning_loop(wa_id, s_refreshed, msg_type="", text="", meta={"trigger": "initial_flights"})
                return

            elif user_input == "more":
                next_hotel_page = current_hotel_page + 1
                start_index = (next_hotel_page - 1) * hotel_page_size
                if start_index < len(all_hotels):
                    await session_svc.update_session_field(wa_id, "hotel_page", next_hotel_page)
                    session["hotel_page"] = next_hotel_page
                    await session_svc.update_session_field(wa_id, "hotels_shown_this_page", False)
                    s_refreshed = session_svc.get(wa_id)
                    await _planning_loop(wa_id, s_refreshed, msg_type="", text="", meta={"trigger": "initial_hotels"})
                else:
                    await whatsapp_client.send_text(wa_id, "No more hotels to show.")
                return
            
            else: # Try to parse number for hotel (Keep existing selection logic)
                if user_input.isdigit():
                    index = int(user_input) - 1
                    last_shown_map = session.get("last_shown_hotels_map", {})
                    hotel_to_add = last_shown_map.get(index + 1)

                    if hotel_to_add:
                        plan["hotel"] = hotel_to_add # Replace if one was already there
                        plan["hotel_ids"] = [hotel_to_add["id"]]
                        await whatsapp_client.send_text(wa_id, f"Selected hotel: {hotel_to_add.get('name', 'Chosen Hotel')}. Moving to flights.")
                        await session_svc.update_session_field(wa_id, "planning_step", "flights")
                        await session_svc.update_session_field(wa_id, "flights_shown_this_round", False)
                        s_refreshed = session_svc.get(wa_id)
                        await _planning_loop(wa_id, s_refreshed, msg_type="", text="", meta={"trigger": "initial_flights"})
                    else:
                        await whatsapp_client.send_text(wa_id, "Invalid selection. Please pick a number from the list.")
                else:
                    await whatsapp_client.send_text(wa_id, "Sorry, I didn't understand. Select a hotel by number, or type 'more' or 'skip'/'done'.")
                return
        return # End of hotels step

    # ---------- Flights (Request 7 will make this complex) ---------- #
    elif step == "flights":
        if meta.get("trigger") == "initial_flights" and not session.get("flights_shown_this_round"): # Renamed session variable
            # This will be entirely replaced by Request 7 logic.
            # For now, let's make it a placeholder that skips to summary.
            await whatsapp_client.send_text(wa_id, "Flight selection will be updated. For now, let's proceed.")
            await session_svc.update_session_field(wa_id, "flights_shown_this_round", True) # Mark as shown/skipped
            session["flights_shown_this_round"] = True
            await session_svc.update_session_field(wa_id, "planning_step", "summary")
            s_refreshed = session_svc.get(wa_id)
            await _planning_loop(wa_id, s_refreshed, msg_type="", text="", meta={}) 
            return

        # Placeholder for actual flight interaction based on Request 7
        # If user types "done" or "skip" during flight interaction (once built)
        if text.strip().lower() in ["done", "skip"] and session.get("flights_shown_this_round"):
            await whatsapp_client.send_text(wa_id, "Okay, flight selection noted.")
            await session_svc.update_session_field(wa_id, "planning_step", "summary")
            s_refreshed = session_svc.get(wa_id)
            await _planning_loop(wa_id, s_refreshed, msg_type="", text="", meta={}) 
            return
        return # End of flights step for now, pending Request 7

    # ---------- Summary & Confirmation (Request 8 for final message) ---------- #
    elif step == "summary":
        summary_text = await _plan_summary(wa_id, session)
        final_message_main = f"✈️ Perfect – Your trip is shaping up nicely!\n\n{summary_text}"
        final_message_followup = "Please review your selections. Once you confirm, we can finalize this. You can also ask to 'restart planning' or 'edit activities/hotel/flights'."
        
        await whatsapp_client.send_text(wa_id, final_message_main)
        await whatsapp_client.send_text(wa_id, final_message_followup)
        
        await session_svc.update_session_field(wa_id, "planning_step", "confirmation")
        await whatsapp_client.send_reply_buttons(
            wa_id, 
            header="Confirm Plan", 
            body="Is this plan correct?", 
            buttons=[{"id": "confirm_plan_yes", "title": "Yes, Looks Good!"}, {"id": "confirm_plan_edit", "title": "Edit Something"}]
        )
        return

    elif step == "confirmation":
        if msg_type == "interactive" and meta.get("button_id") == "confirm_plan_yes":
            summary_text = await _plan_summary(wa_id, session) 
            confirmation_main = f"✈️ Perfect – Your trip is ready to go!\n\nHere is a summary:\n{summary_text}"
            confirmation_followup = "Please wait for us to send you an itinerary with a tentative quote."
            
            await whatsapp_client.send_text(wa_id, confirmation_main)
            await whatsapp_client.send_text(wa_id, confirmation_followup)
            
            await session_svc.set_state(wa_id, "COMPLETED") 
            await session_svc.update_session_field(wa_id, "planning_step", "finished")
        elif msg_type == "interactive" and meta.get("button_id") == "confirm_plan_edit":
            await whatsapp_client.send_text(wa_id, "Sure, what would you like to change? (e.g., 'change activities', 'update budget', 'pick different hotel')")
            await session_svc.update_session_field(wa_id, "planning_step", "ask_for_edits") 
        else:
            await whatsapp_client.send_text(wa_id, "Please use the buttons to confirm or let me know if you'd like to edit something.")
        return
        
    elif step == "ask_for_edits":
        # This is where LLM would parse the edit request. For example:
        if "activit" in text.lower(): # very simple keyword check
            await whatsapp_client.send_text(wa_id, "Okay, let's change activities.")
            await session_svc.update_session_field(wa_id, "planning_step", "activities")
            await session_svc.update_session_field(wa_id, "activities_shown_this_round", False) 
            await session_svc.update_session_field(wa_id, "activity_page", 1) # Reset page
             # Clear previous activity selections from plan if redoing
            plan["activities"] = []
            plan["activity_ids"] = []
            s_refreshed = session_svc.get(wa_id)
            await _planning_loop(wa_id, s_refreshed, msg_type="", text="", meta={"trigger": "initial_activities"})
        else:
            await whatsapp_client.send_text(wa_id, f"I've noted you want to make changes. Text me what you'd like to modify, for example: 'I want to change destination to Paris' or 'remove activity 2'.")
        return


    logger.warning(f"Unhandled state in _planning_loop: step={step}, text='{text}'")


async def _show_activities(wa_id: str, acts: List[dict]):
    if not acts:
        await whatsapp_client.send_text(wa_id, "Sorry, I couldn't find any activities for you right now.")
        return

    # Text before sending activities list is fine
    # await whatsapp_client.send_text(wa_id, "Here are some activities you might like:")
    
    # Key change: Store a map of the currently displayed items for selection by number
    # The map will be {display_number: full_activity_object}
    current_display_map = {}

    for i, act in enumerate(acts, 1): # acts are full activity objects from backend
        activity_name = act.get("title", "Unnamed Activity")
        caption = f"{i}. {activity_name}" 
        image_url = act.get("images")
        
        current_display_map[i] = act

        if image_url and "placehold.it" not in image_url:
            await whatsapp_client.send_image(wa_id, image_url=image_url, caption=caption)
        else:
            # If image_url is missing OR it's a placehold.it URL, send as text
            await whatsapp_client.send_text(wa_id, caption)
        
        await asyncio.sleep(0.5) 
    
    # Store this map in session to be used by _planning_loop for selection
    await session_svc.update_session_field(wa_id, "last_shown_activities_map", current_display_map)
    # current_activity_options (list of {"id": ..., "title": ...}) is no longer primary for selection by number, map is.
    # Can keep it if interactive messages are a fallback or used elsewhere.

async def _show_hotels(wa_id: str, hotels: List[dict]):
    if not hotels:
        await whatsapp_client.send_text(wa_id, "Sorry, I couldn't find any hotels for you right now.")
        return

    # await whatsapp_client.send_text(wa_id, "Here are some hotel options:")
    current_display_map = {}

    for i, hotel in enumerate(hotels, 1): # hotels are full objects
        hotel_name = hotel.get("title", "Unnamed Hotel")
        caption = f"{i}. {hotel_name}" 
        image_url = hotel.get("images")
        
        current_display_map[i] = hotel

        if image_url:
            await whatsapp_client.send_image(wa_id, image_url=image_url, caption=caption)
        else:
            await whatsapp_client.send_text(wa_id, caption)
            
        await asyncio.sleep(0.5)
        
    await session_svc.update_session_field(wa_id, "last_shown_hotels_map", current_display_map)

async def _plan_summary(wa_id: str, session: dict) -> str:
    plan = session.get("plan", {})
    reqs = session["requirements"]
    
    lines = [f"📝 *Trip for {reqs.get('customer_name', 'You')} to {reqs.get('destination_city', 'your destination')}*"]
    lines.append(f"From: {reqs.get('start_date', 'N/A')} to {reqs.get('end_date', 'N/A')}")
    
    selected_activities = plan.get("activities", [])
    if selected_activities:
        lines.append("\n*Selected Activities:*")
        for i, act_session_data in enumerate(selected_activities, 1):
            # Assuming act_session_data stored in plan is the full activity dict or has 'name'
            lines.append(f"  {i}. {act_session_data.get('name', 'Unknown Activity')}")
    else:
        lines.append("\n*Selected Activities:* None")

    selected_hotel = plan.get("hotel") # Assuming hotel is a dict with 'name'
    if selected_hotel:
        lines.append(f"\n*Selected Hotel:* {selected_hotel.get('name', 'Unknown Hotel')}")
    else:
        lines.append("\n*Selected Hotel:* None")

    selected_flight = plan.get("flight") # Assuming flight is a dict with details
    if selected_flight:
        lines.append(f"\n*Selected Flight:* {selected_flight.get('airline', 'Unknown Airline')} - {selected_flight.get('flight_number', '')}") # Example
    else:
        lines.append("\n*Selected Flight:* None")
        
    # Request 4: No prices in summary either
    # lines.append(f"\nEstimated Total: ₹{plan.get('total_price_inr', 0)}") # Removed for now

    return "\n".join(lines)


conv_flow = ConversationFlow()

