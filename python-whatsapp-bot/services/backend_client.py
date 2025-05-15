import httpx
import os
import logging
from config.env import BACKEND_URL

logger = logging.getLogger(__name__)

BACKEND_URL = BACKEND_URL.rstrip("/")


async def get_activities(city: str) -> list[dict]:
    params = {"city": city.title()}
    async with httpx.AsyncClient() as c:
        r = await c.get(f"{BACKEND_URL}/activities", params=params, timeout=8)
        r.raise_for_status()
        return r.json()


async def get_hotels(city: str) -> list[dict]:
    params = {"city": city.title()}
    async with httpx.AsyncClient() as c:
        r = await c.get(f"{BACKEND_URL}/hotels", params=params, timeout=8)
        r.raise_for_status()
        return r.json()


async def get_flights(dest_code: str, depart_date: str, limit: int = 2) -> list[dict]:
    params = {"destination": dest_code.upper(), "depart_date": depart_date}
    async with httpx.AsyncClient() as c:
        r = await c.get(f"{BACKEND_URL}/flights", params=params, timeout=8)
        r.raise_for_status()
        return r.json()[:limit]


async def create_or_update_plan(session: dict) -> None:
    """
    Push the current plan dict to /plan_list.
    If session['plan_id'] is None → creates, else updates.
    """
    payload = session["plan"].copy()
    pid = session.get("plan_id")
    if pid is None:
        payload["id"] = "new"
        payload["requirement_id"] = session["backend_id"]
    else:
        payload["id"] = pid

    async with httpx.AsyncClient() as c:
        r = await c.post(f"{BACKEND_URL}/plan_list", json=payload, timeout=10)
        r.raise_for_status()
        data = r.json()
        session["plan_id"] = data["id"]  # store ID after first creation

async def generate_itinerary() -> dict:
    """Generate itinerary for a plan using the RFI endpoint."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{BACKEND_URL}/rfi",
            json={"plan_id": 1}
        )
        resp.raise_for_status()
        return resp.json()
