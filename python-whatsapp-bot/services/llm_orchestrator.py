import json
import logging
from openai import OpenAI
from config.prompts import SYSTEM_PROMPT, USER_PROMPT
from config.env import OPENAI_API_KEY

logger = logging.getLogger(__name__)

class LLMOrchestrator:
    """Builds prompts, calls the LLM, and parses responses."""
    def __init__(self, api_key: str, model: str = "gpt-4o-mini"):
        self.client = OpenAI(api_key=api_key)
        self.model = model

    async def generate_response(self, session: dict, user_message: str) -> dict:
        history = "\n".join(session.get('history', []))
        system_msg = SYSTEM_PROMPT
        user_msg = USER_PROMPT.format(
            conversation_history=history,
            message_body=user_message,
            requirement_state=json.dumps(session["requirements"])
        )

        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role":"system","content":system_msg},
                    {"role":"user","content":user_msg}
                ]
            )
            raw = resp.choices[0].message.content.strip()
            logger.info(f"LLM raw response: {raw}")
            parsed = json.loads(raw)
            # ensure keys
            for k in ('reply','next_state','update'):
                if k not in parsed:
                    raise ValueError(f"Missing {k} in LLM response")
            return parsed
        except Exception as e:
            logger.error(f"LLM error: {e}")
            return {"reply":"Oops, something went wrong.","next_state":None,"update":{}}
        
llm = LLMOrchestrator(api_key=OPENAI_API_KEY)