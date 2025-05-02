import httpx
import io
from openai import OpenAI
from config.env import ACCESS_TOKEN

openaiclient = OpenAI()
async def transcribe_audio_from_whatsapp(media_id: str) -> str:
    """
    Download audio from WhatsApp (into memory) and transcribe it with Whisper.
    """
    # 1. Get the direct download URL
    media_url = f"https://graph.facebook.com/v19.0/{media_id}"
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
    async with httpx.AsyncClient() as client:
        meta = await client.get(media_url, headers=headers)
        meta.raise_for_status()
        download_url = meta.json()["url"]

        # 2. Fetch the actual audio bytes
        audio_resp = await client.get(download_url, headers=headers)
        audio_resp.raise_for_status()
        audio_bytes = audio_resp.content

    # 3. Wrap bytes in a file-like object
    audio_file = io.BytesIO(audio_bytes)
    audio_file.name = "voice.ogg"  # Whisper checks .name to infer format

    # 4. Transcribe with Whisper
    print("Transcribing audio...")
    transcript = openaiclient.audio.translations.create(model="whisper-1", file=audio_file)
    print("Transcription complete")
    print("TRanscript==================",transcript)
    return transcript.text
