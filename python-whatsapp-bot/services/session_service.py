import httpx
from datetime import datetime
import logging
import json
from typing import Optional
from config.env import BACKEND_URL

logger = logging.getLogger(__name__)


class SessionService:
    """
    In-memory session + requirement + plan sync.
    """
    def __init__(self, api_base: str):
        self.api_base = api_base.rstrip("/")
        self.sessions: dict[str, dict] = {}

    # ------------------- requirement sheet ---------------------------- #

    async def init_session(self, wa_id: str, profile_name: str):
        self.sessions[wa_id] = {
            "state": "GREETING",
            "history": [],
            "requirements": {
                "customer_name": profile_name,
                "pax": [],
                "departure_city": None,
                "destination_city": None,
                "budget_inr": None,
                "start_date": None,
                "end_date": None,
            },
            "backend_id": None,
            "plan": {
                "activity_ids": [],
                "activities":   [],      # full dicts go here
                "hotel_ids":    [],
                "hotel":        None,    # full dict
                "flight_ids":   [],
                "flight":       None,    # full dict
                "total_price_inr": 0,
            },
            "plan_id": None,
            "last_activity": datetime.utcnow().isoformat(),
        }
        await self._sync_req(wa_id, {"customer_name": profile_name})

    def get(self, wa_id: str) -> Optional[dict]:
        return self.sessions.get(wa_id)

    async def update_requirements(self, wa_id: str, patch: dict):
        # normalise "null"/"" → None
        for k, v in list(patch.items()):
            if isinstance(v, str) and v.strip().lower() in {"null", "none", ""}:
                patch[k] = None
        self.sessions[wa_id]["requirements"].update(patch)
        await self._sync_req(wa_id, patch)

    async def set_state(self, wa_id: str, state: str):
        s = self.sessions[wa_id]
        s["state"] = state
        s["last_activity"] = datetime.utcnow().isoformat()

    async def delete_session(self, wa_id: str):
        if wa_id in self.sessions:
            del self.sessions[wa_id]
            logger.info(f"Session deleted for wa_id: {wa_id}")
        else:
            logger.info(f"No session found for wa_id: {wa_id} to delete")

    async def _sync_req(self, wa_id: str, patch: dict):
        s = self.sessions[wa_id]
        payload = {"id": "new" if s["backend_id"] is None else s["backend_id"]}
        payload.update(patch)
        logger.info("↗ POST /req_list  payload=%s", json.dumps(payload, ensure_ascii=False))
        async with httpx.AsyncClient() as c:
            r = await c.post(f"{self.api_base}/req_list", json=payload, timeout=10)
            r.raise_for_status()
            data = r.json()
            s["backend_id"] = data["id"]


session_svc = SessionService(api_base=BACKEND_URL)
