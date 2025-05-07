import httpx
import os
from config.env import BACKEND_URL

BACKEND_URL = BACKEND_URL.rstrip("/")


async def get_activities(city: str, limit: int = 6) -> list[dict]:
    params = {"city": city.title()}
    async with httpx.AsyncClient() as c:
        r = await c.get(f"{BACKEND_URL}/activities", params=params, timeout=8)
        r.raise_for_status()
        return r.json()[:limit]


async def get_hotels(city: str, limit: int = 3) -> list[dict]:
    params = {"city": city.title()}
    async with httpx.AsyncClient() as c:
        r = await c.get(f"{BACKEND_URL}/hotels", params=params, timeout=8)
        r.raise_for_status()
        return r.json()[:limit]


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
