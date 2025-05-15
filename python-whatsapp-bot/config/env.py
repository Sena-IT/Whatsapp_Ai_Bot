import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
APP_ID = os.getenv("APP_ID")
APP_SECRET = os.getenv("APP_SECRET")
RECIPIENT_WAID = os.getenv("RECIPIENT_WAID")
VERSION = os.getenv("VERSION", "v22.0")  # Default to v22.0 if not set
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
BACKEND_URL = os.getenv("BACKEND_URL")
FACEBOOK_API_BASE = os.getenv("FACEBOOK_API_BASE")
CARTESIA_API_KEY = os.getenv("CARTESIA_API_KEY")
# Validate required environment variables
def validate_env():
    required_vars = ["OPENAI_API_KEY", "ACCESS_TOKEN", "APP_ID", "APP_SECRET", "RECIPIENT_WAID", "VERSION", "PHONE_NUMBER_ID", "VERIFY_TOKEN", "CARTESIA_API_KEY"]
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    if missing_vars:
        raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")
