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
from config.env import ITINERARY_BUILDER_BASE_URL

from utils.whatsapp_utils import extract_message_details, transcribe_audio_from_whatsapp, upload_audio_to_meta_cloud, delete_uploaded_file, upload_file_to_meta_cloud

logger = logging.getLogger(__name__)


REQ_KEYS = ["destination_city", "pax", "departure_city",
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


class ConversationFlow:
    

    async def handle_event(self, body: Dict[str, Any]) -> None:
        ok, wa_id, profile_name, payload = extract_message_details(body)
        if not ok:
            return
        
        await self._process(wa_id, profile_name, payload)

    # =================== MAIN STATE MACHINE ========================= #
    async def _process(self, wa_id: str, profile_name: str, payload: Dict[str, Any]):
        s = session_svc.get(wa_id)
        user_message_text = payload.get("text", "").strip().lower() # Get text from payload

        # ---- Keyword-based session reset ---------------------------- #
        # Check if an existing session should be reset by keyword
        if s and user_message_text in ["reset demo"]:
            logger.info(f"Reset keyword '{user_message_text}' detected from {wa_id}. Deleting session.")
            await session_svc.delete_session(wa_id)
            s = None # Crucial: Set s to None to trigger the new visitor logic below

        # ---- new visitor or session just reset via keyword ---------- #
        if not s:
            logger.info(f"Initializing session for {wa_id} (new visitor or after reset).")
            await session_svc.init_session(wa_id, profile_name)
            await whatsapp_client.send_reply_buttons(
                wa_id,
                header="Welcome to Sena Holidays!",
                body=f"Hello {profile_name}! I'm Lila, your travel planning assistant.",
                buttons=[{"id": "start_planning", "title": "Start Planning"}],
            )
            return

        # ---- duplicate WA delivery? -------------------------------- #
        if payload.get("meta", {}).get("message_id") == s.get("last_msg_id"):
            return
        s["last_msg_id"] = payload.get("meta", {}).get("message_id")

        msg_type = payload["type"]
        msg_text = payload["text"]
        meta = payload.get("meta", {})

        if s["state"] == "PLANNING":
            await _planning_loop(wa_id, s, msg_type, msg_text, meta)
            return
    
        # ---- POST REQUIREMENT CHOICE State Handler ------------------ #
        if s["state"] == "POST_REQUIREMENT_CHOICE":
            if msg_type == "interactive":
                button_id = meta.get("button_id")
                if button_id == "continue_on_whatsapp":
                    await session_svc.set_state(wa_id, "PLANNING")
                    await whatsapp_client.send_text(
                        wa_id,
                        "✅ All set! Let's plan flights, hotels and fun activities next. "
                        "What would you like to start with?",
                    )
                    await _planning_loop(wa_id, s, "", "", {})  # Start planning
                elif button_id == "open_itinerary_builder":
                    if s.get("plan_id"):
                        builder_url = f"{ITINERARY_BUILDER_BASE_URL}?itineraryId={s['plan_id']}" 
                        await whatsapp_client.send_text(wa_id, f"Great! You can build your own itinerary here: {builder_url}")
                    else:
                        logger.error(f"plan_id not found in session for wa_id {wa_id} when trying to generate builder URL.")
                        await whatsapp_client.send_text(wa_id, "Sorry, I couldn't create the link for the itinerary builder at the moment. Please try again.")
                    # Consider what state to transition to. GREETING resets the flow for a new plan.
                    await session_svc.set_state(wa_id, "GREETING") 
                    await whatsapp_client.send_text(wa_id, "Let me know if there's anything else I can help you with!")
                else: 
                    await whatsapp_client.send_text(wa_id, "Please choose one of the options by tapping a button.")
            else: # Not an interactive reply
                await whatsapp_client.send_text(wa_id, "Please tap one of the buttons to proceed.")
            return
    
        # ---- GREETING → REQUIREMENT trigger ------------------------ #
        if s["state"] == "GREETING":
            if msg_type == "interactive" and meta.get("button_id") == "start_planning":
                await session_svc.set_state(wa_id, "REQUIREMENT")
                await whatsapp_client.send_text(
                    wa_id,
                    "Awesome – I'd love to help you plan your trip! "
                    "Let's figure out the details below. 😊",
                )
                await whatsapp_client.send_text(wa_id, _sheet(s))
            return

        # ---- REQUIREMENT interactive destination pick -------------- #
        if s["state"] == "REQUIREMENT" and msg_type == "interactive":
            list_id = meta.get("list_id") or meta.get("button_id")
            if list_id and list_id.startswith("dest_"):
                city = list_id.split("_", 1)[1].title()
                await session_svc.update_requirements(wa_id, {"destination_city": city})
                await whatsapp_client.send_text(wa_id, f"Great choice – {city} it is! 🛫")
                if _should_show_sheet(s, {"destination_city": city}):
                    await whatsapp_client.send_text(wa_id, _sheet(s))
                return

        # ---- voice → text ------------------------------------------ #
        if msg_type == "audio":
            tr = await transcribe_audio_from_whatsapp(meta["audio_id"])
            if tr:
                await whatsapp_client.send_text(wa_id, f'I heard: "{tr}"')
                msg_text = tr
            else:
                await whatsapp_client.send_text(wa_id, "Sorry, didn't catch that. Please type 🙂")
                return

        # ---- LLM call --------------------------------------------- #
        resp = await llm.generate_response(s, msg_text)
        logger.info("LLM result: %s", resp)

        if resp.get("update"):
            await session_svc.update_requirements(wa_id, resp["update"])
            if _should_show_sheet(s, resp["update"]):
                await whatsapp_client.send_text(wa_id, _sheet(s))

        # ---- auto flip to POST_REQUIREMENT_CHOICE (modified from PLANNING) ---- #
        if s["state"] == "REQUIREMENT" and _complete(s["requirements"]):
            destination_city = s["requirements"].get("destination_city", "").title()
            
            pdf_path = None
            pdf_caption = None
            pdf_filename = None

            if "Singapore" in destination_city:
                pdf_path = "assets/Singaporeitinerary.pdf"
                pdf_caption = "Here is a sample itinerary for Singapore."
                pdf_filename = "Singaporeitinerary.pdf"
            elif "Bali" in destination_city:
                pdf_path = "assets/Baliitinerary.pdf"
                pdf_caption = "Here is a sample itinerary for Bali."
                pdf_filename = "Baliitinerary.pdf"
            elif "Dubai" in destination_city:
                pdf_path = "assets/Dubaiitinerary.pdf"
                pdf_caption = "Here is a sample itinerary for Dubai."
                pdf_filename = "Dubaiitinerary.pdf"
            
            if pdf_path: # Proceed only if a PDF path was determined
                try:
                    media_id = await upload_file_to_meta_cloud(pdf_path, "application/pdf")
                    if media_id:
                        await whatsapp_client.send_document(wa_id, media_id, filename=pdf_filename, caption=pdf_caption)
                        await delete_uploaded_file(media_id) 
                    else:
                        logger.error(f"Failed to get media_id for PDF: {pdf_path}")
                        await whatsapp_client.send_text(wa_id, "Sorry, I couldn't send the sample itinerary PDF at the moment.")
                except FileNotFoundError:
                    logger.error(f"Itinerary PDF not found at {pdf_path}")
                    await whatsapp_client.send_text(wa_id, "Sorry, the sample itinerary PDF is currently unavailable for your chosen destination.")
                except Exception as e:
                    logger.error(f"Error sending PDF {pdf_path}: {e}")
                    await whatsapp_client.send_text(wa_id, "Sorry, an error occurred while sending the sample itinerary.")
            else:
                logger.info(f"No specific sample itinerary PDF found for destination: {destination_city}. Skipping PDF send.")
                # Optionally send a message to the user, e.g.:
                # await whatsapp_client.send_text(wa_id, "A general sample itinerary will be prepared for you shortly.")

            # Ensure a plan is created/updated in the backend before showing options
            try:
                await backend_client.create_or_update_plan(s)
                logger.info(f"Plan {s.get('plan_id', 'new')} for requirement {s['backend_id']} synced with backend.")
                
                # Now that plan_id is confirmed, call RFI
                if s.get("plan_id"):
                    logger.info(f"Calling RFI for plan_id: {s['plan_id']}")
                    rfi_response = await backend_client.generate_itinerary(s["plan_id"])
                    logger.info(f"RFI call for plan_id {s['plan_id']} successful. Response: {rfi_response}")
                    # Store or use rfi_response as needed, e.g., s["rfi_data"] = rfi_response
                else:
                    logger.error(f"Cannot call RFI: plan_id is missing after create_or_update_plan for requirement {s['backend_id']}.")

            except Exception as e:
                logger.error(f"Error syncing plan with backend or calling RFI before POST_REQUIREMENT_CHOICE: {e}")
                # Decide if we should still proceed or inform user of an error
                # For now, let's proceed but this could be a point of failure

            # Send buttons
            button_header = "Customize itinerary or use builder"
            button_body = "You can customize your itinerary on WhatsApp or check out our detailed Itinerary Builder"
            await whatsapp_client.send_reply_buttons(
                wa_id,
                header=button_header, 
                body=button_body,
                buttons=[
                    {"id": "continue_on_whatsapp", "title": "Stay on WhatsApp"},
                    {"id": "open_itinerary_builder", "title": "Open Builder"}
                ],
            )
            await session_svc.set_state(wa_id, "POST_REQUIREMENT_CHOICE")
            return  # End turn here, wait for button press

        # ---- still in REQUIREMENT: maybe send suggestions ---------- #
        if (
            s["state"] == "REQUIREMENT"
            and not s["requirements"]["destination_city"]
            and not s.get("suggestions_shown")
        ):
            s["suggestions_shown"] = True
            await _send_destinations_bundle(wa_id)

        # ---- in PLANNING ------------------------------------------- #
        

        # ---- default reply ----------------------------------------- #
        if msg_type == "audio":
            audio_path = await tts.generate_audio(resp["reply"])
            if not audio_path:
                return False
            
            media_id = await upload_audio_to_meta_cloud(audio_path)
            if not media_id:
                return False
            
            response_code = await whatsapp_client.send_audio(wa_id, media_id)
            if os.path.exists(audio_path):
                os.remove(audio_path)
            
            if response_code == 200:
                await delete_uploaded_file(media_id)
                return True
            return False
        else:
            await whatsapp_client.send_text(wa_id, resp["reply"])
        
        s["history"].extend([f"User: {msg_text}", f"Bot: {resp['reply']}"])


def _sheet(session: dict) -> str:
    r = session["requirements"]
    
    return "\n".join([
        "📝 *Your trip requirement sheet*",
        f"Name: {r['customer_name'] or '—'}",
        f"Pax: {r['pax'] or '—'}",
        f"Departure city: {r['departure_city'] or '—'}",
        f"Destination: {r['destination_city'] or '—'}",
        f"Budget (₹): {r['budget_inr'] or '—'}",
        f"Start date: {r['start_date'] or '—'}",
        f"End date: {r['end_date'] or '—'}",
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
    plan = session["plan"]
    dest = session["requirements"]["destination_city"]
    logging.info(f"text: {text}")
    logging.info(f"msg_type: {msg_type}")
    logging.info(f"step: {step}")

    # ---------- initial ask ---------------------------------------- #
    if step == "ask":
        await whatsapp_client.send_list(
            wa_id,
            header="What shall we plan first?",
            body="Pick one of these to continue:",
            options=[
                {"id": "plan_activities", "title": "Activities"},
                {"id": "plan_hotels",     "title": "Hotels"},
                {"id": "plan_flights",    "title": "Flights"},
            ],
            button="Choose",
        )
        session["planning_step"] = "waiting_choice"
        return

    # ---------- wait for the user's choice ------------------------ #
    if step == "waiting_choice":
        chosen = meta.get("button_id") or meta.get("list_id")  
        logging.info(f"chosen: {chosen}")          # user tapped a list-item
        if not chosen:                          # or typed the word
            lw = text.lower()
            if "activity" in lw:
                chosen = "plan_activities"
            elif "hotel" in lw:
                chosen = "plan_hotels"
            elif "flight" in lw:
                chosen = "plan_flights"

        if not chosen:
            await whatsapp_client.send_text(
                wa_id,
                "Just tap *Activities*, *Hotels* or *Flights* 🙂"
            )
            return

        # ── update step & immediately re-enter the loop ───────────
        session["planning_step"] = (
        "activities" if chosen == "plan_activities"
        else "hotels" if chosen == "plan_hotels"
        else "flights"
    )

        # call the loop again with blank message to continue flow
        await _planning_loop(wa_id, session, "", "", {})
        return    
    
    if step == "activities":
        acts = await backend_client.get_activities(dest)
        logging.info(f"acts: {acts}")
        await _show_activities(wa_id, acts)
        session["planning_step"] = "activities_pick"
        session["pending_activities"] = {str(a["id"]): a for a in acts}
        return

    if step == "activities_pick":
        sel_id = (meta.get("list_id") or meta.get("button_id"))
        aid    = sel_id.replace("act_", "") if sel_id else ""
        pend   = session.get("pending_activities", {})

        # 1. The user tapped a row
        if msg_type == "interactive" and aid in pend:
            plan["activity_ids"].append(int(aid))
            plan.setdefault("activities", []).append(pend[aid])
            plan["total_price_inr"] += pend[aid]["price_inr"]
            await backend_client.create_or_update_plan(session)
            await whatsapp_client.send_text(
                wa_id, "✔️ Added!  Pick more or type *Done* when you're finished."
            )
            return

        # 2. The user typed "done"
        if msg_type == "text" and text.casefold().strip() == "done":
            logging.info("Reached done. we are here.")
            session.pop("pending_activities", None)
            session["planning_step"] = "hotels"
            await _planning_loop(wa_id, session, "", "", {})   # jump forward
            return

        # 3. Anything else – gentle reminder
        if msg_type == "text":
            await whatsapp_client.send_text(
                wa_id, "Just tap another activity or type *Done*."
            )
        return

    # ---------- hotels list & pick ----------------------------- #
    if step == "hotels":
        hotels = await backend_client.get_hotels(dest)
        await _show_hotels(wa_id, hotels)
        session["planning_step"] = "hotels_pick"
        session["pending_hotels"] = {str(h["id"]): h for h in hotels}
        return

    if step == "hotels_pick" and msg_type == "interactive":
        logging.info(f"Reached hotels_pick")
        hid  = (meta.get("list_id") or meta.get("button_id") or "").replace("hotel_", "")
        pend = session.get("pending_hotels", {})
        if hid in pend:
            plan["hotel_ids"] = [int(hid)]
            plan["hotel"]     = pend[hid]
            plan["total_price_inr"] += pend[hid]["base_rate_inr"]
            await backend_client.create_or_update_plan(session)
            session.pop("pending_hotels", None)
            session["planning_step"] = "flights"
            step = "flights"                   # fall through

    # ---------- flights list & pick ---------------------------- #
    if step == "flights":
        iata_map = {
        "Bali": "DPS",
        "Dubai": "DXB",
        "Singapore": "SIN",
    }
        iata = iata_map.get(dest, dest[:3]).upper()
        flights = await backend_client.get_flights(
            dest_code=iata,    # crude mapping: SIN/DPS/DXB expected
            depart_date=session["requirements"]["start_date"],
        )
        await _show_flights(wa_id, flights)
        session["planning_step"] = "flights_pick"
        session["pending_flights"] = {str(f["id"]): f for f in flights}
        return

    if step == "flights_pick" and msg_type == "interactive":
        fid  = (meta.get("button_id") or "").replace("flight_", "")
        pend = session.get("pending_flights", {})
        if fid in pend:
            plan["flight_ids"] = [int(fid)]
            plan["flight"]     = pend[fid]
            plan["total_price_inr"] += pend[fid]["price_inr"]
            await backend_client.create_or_update_plan(session)
            session.pop("pending_flights", None)
            session["planning_step"] = "summary"
            await whatsapp_client.send_text(wa_id, "✈️ Perfect – Your trip is ready to go!")
            step = "summary"                   # fall through

    # ---------- summary ---------------------------------------- #
    if step == "summary":
        logging.info(f"Reached summary. Updating plan for plan_id: {session.get('plan_id')}")
        
        # Send the plan summary text first
        summary_text = await _plan_summary(wa_id, session)
        await whatsapp_client.send_text(wa_id, summary_text)

        try:
            # Update the plan in the backend with final selections
            if session.get("plan_id"):
                await backend_client.create_or_update_plan(session)
                logger.info(f"Plan {session['plan_id']} updated successfully in backend.")
                
                # Regenerate RFI with the updated plan
                rfi_response = await backend_client.generate_itinerary(session["plan_id"])
                logger.info(f"RFI regenerated for plan_id {session['plan_id']}. Response: {rfi_response}")
                
                # Send the builder URL only after successful RFI regeneration
                builder_url = f"{ITINERARY_BUILDER_BASE_URL}?itineraryId={session['plan_id']}"
                await whatsapp_client.send_text(wa_id, f"You can also build and further customize your itinerary here: {builder_url}")
            else:
                logger.error(f"Cannot update plan or regenerate RFI (and thus cannot send builder link): plan_id missing in session summary step for wa_id: {wa_id}")
                # Do not send builder link if plan_id is missing. Summary already sent.
        except Exception as e:
            logger.error(f"Exception caught in summary step for plan_id {session.get('plan_id')}: {e}", exc_info=True)
            # Inform user about RFI failure, but summary was already sent.
            await whatsapp_client.send_text(wa_id, f"Sorry, there was an issue preparing the detailed itinerary link. Your summary is above. {e}")

        session["planning_step"] = "END" # Transition to an end state
        return



async def _show_activities(wa_id: str, acts: List[dict]):
    for a in acts:

        image_url = "https://cdn.pixabay.com/photo/2018/01/03/19/17/cat-3059075_1280.jpg" # Default if no images
        if a.get("images"):
            image_url = a["images"].strip()

        await whatsapp_client.send_image(
            wa_id,
            image_url= image_url,
            caption=f"{a['title']} – ₹{a['price_inr']:,}"
        )
    await asyncio.sleep(2)
    await whatsapp_client.send_list(
        wa_id,
        header="Pick an activity",
        body="Tap to add to your plan:",
        options=[
        {
            "id": f"act_{a['id']}",
            "title": a["title"][:24]                              # hard-limit
        }
        for a in acts                                        # Facebook list limit
    ],
        button="Activities",
    )


async def _show_hotels(wa_id: str, hotels: List[dict]):
    for h in hotels:
        # Get the image URL directly, stripping whitespace
        image_url = "https://cdn.pixabay.com/photo/2018/01/03/19/17/cat-3059075_1280.jpg" # Default if no images
        if h.get("images"):
            image_url = h["images"].strip()


        await whatsapp_client.send_image(
            wa_id,
            image_url=image_url,
            caption=f"{h['name']} ({h['star']}★)",
        )
    await asyncio.sleep(1)
    await whatsapp_client.send_list(
        wa_id,
        header="Hotels",
        body="Pick one:",
        options=[{"id": f"hotel_{h['id']}", "title": h["name"][:24]} for h in hotels],
        button="Hotels",
    )

_MAX_WA_TITLE = 24

def _trim(title: str) -> str:
    """Return title ≤24 chars; add … if we truncated."""
    return (title[: _MAX_WA_TITLE - 1] + "…") if len(title) > _MAX_WA_TITLE else title

async def _show_flights(wa_id: str, flights: List[dict]):
    
    rows = [
        {
            "id":   f"flight_{f['id']}",
            "title": _trim(f"{f['airline']} – ₹{f['price_inr']:,}")
        }
        for f in flights
    ]
    try:
        await whatsapp_client.send_list(
            wa_id,
            header="Flights",
            body="Pick a flight option:",
            options=rows,
            button="Flights",
        )
    except Exception as exc:                    
        logger.exception("Failed to send flight list → %s", exc)


async def _plan_summary(wa_id: str,session: dict) -> str:
    p      = session["plan"]
    hotel  = p.get("hotel")
    flight = p.get("flight")
    activities = p.get("activities", [])

    hotel_line = (
        f"{hotel['name']} ({hotel['star']}★) – ₹{hotel['base_rate_inr']:,}/night"
        if hotel else "—"
    )

    flight_line = (
        f"{flight['airline']} {flight['flight_number']} "
        f"({flight['origin']}→{flight['destination']}) – ₹{flight['price_inr']:,}"
        if flight else "—"
    )

    act_line = (
        "—"
        if not activities
        else ", ".join(
            f"{a['title']} – ₹{a['price_inr']:,}"
            for a in activities
        )
    )
    total     = f"₹{p['total_price_inr']:,}" if p["total_price_inr"] else "—"

    return "\n".join([
        "🧾 *Your draft trip plan*",
        f"Activities : {act_line}",
        f"Hotel      : {hotel_line}",
        f"Flight     : {flight_line}",
        f"*Estimated total*: {total}",
    ])

def _log_history(session: dict, user_msg: str, bot_msg: str):
    session["history"].extend([f"User: {user_msg}", f"Bot: {bot_msg}"])


conv_flow = ConversationFlow()

