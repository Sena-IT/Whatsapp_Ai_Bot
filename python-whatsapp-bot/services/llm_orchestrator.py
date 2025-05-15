import json
import logging
from openai import OpenAI
from config.prompts import SYSTEM_PROMPT, USER_PROMPT
from config.env import OPENAI_API_KEY, CARTESIA_API_KEY
import datetime
from cartesia import Cartesia
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

class LLMOrchestrator:
    """Builds prompts, calls the LLM, and parses responses."""
    def __init__(self, api_key: str, model: str = "gpt-4o-mini"):
        self.client = OpenAI(api_key=api_key)
        self.model = model
        self.system_prompt = SYSTEM_PROMPT.format(
            current_date=datetime.datetime.now().strftime("%B %d, %Y")
        )

    async def generate_response(self, session: dict, user_message: str) -> dict:
        history = "\n".join(session.get('history', []))
        system_msg = self.system_prompt
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
 
 
class TTSOrchestrator:
    """Builds prompts, calls the LLM, and parses responses."""
    def __init__(self):
        self.client = OpenAI(api_key=OPENAI_API_KEY)
        self.model = "tts-1"
        self.voice="alloy"

    async def generate_audio(self, user_message: str) -> dict:
        try:
            speech_file_path = "temp_speech.mp3"
            response = self.client.audio.speech.create(
            model=self.model,
            voice=self.voice,  # You can choose from: alloy, echo, fable, onyx, nova, shimmer
            input=user_message
        )

            # Save the audio file using the recommended streaming approach

            with open(speech_file_path, 'wb') as file:
                for chunk in response.iter_bytes():
                    file.write(chunk)
            return speech_file_path
        except Exception as e:
            logging.error(f"Error in text-to-speech conversion: {e}")
            return None


llm = LLMOrchestrator(api_key=OPENAI_API_KEY)
tts = TTSOrchestrator()