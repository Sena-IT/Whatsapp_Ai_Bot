import openai
import json
import logging
from config.env import OPENAI_API_KEY
from config.prompts import SYSTEM_PROMPT, USER_PROMPT

client = openai.OpenAI(api_key=OPENAI_API_KEY)
logging.basicConfig(level=logging.INFO)

async def generate_llm_response(session: dict, user_message: str) -> str:
    """Send state-aware prompt to LLM."""
    history = "\n".join(session.get("conversation_history", []))
    logging.info(f"History: {history}")
    logging.info(f"User message: {user_message}")


    system_prompt = SYSTEM_PROMPT
    user_prompt = USER_PROMPT.format(
        conversation_history=history,
        message_body=user_message
    )

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
        )
        raw = response.choices[0].message.content.strip()
        logging.info(f"LLM REsponse: {raw}")
        # Try parsing it as JSON
        parsed = json.loads(raw)

        # Validate required keys exist
        if not all(k in parsed for k in ["reply", "next_state", "update"]):
            raise ValueError("Missing required keys in LLM response")

        return parsed

    except (json.JSONDecodeError, ValueError) as e:
        print(f"❌ Error parsing LLM response: {e}")
        return {
            "reply": "Sorry, I didn't quite understand that. Could you rephrase?",
            "complete": False,
            "next_state": None,
            "update": {}
        }
    except Exception as e:
        print(f"LLM fallback error: {e}")
        return {
            "reply": "Something went wrong. Please try again.",
            "complete": False,
            "next_state": None,
            "update": {}
        }