import sys
import os
from dotenv import load_dotenv
import logging
from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import Optional

class Settings(BaseSettings):
    ACCESS_TOKEN: str
    APP_ID: str
    APP_SECRET: str
    RECIPIENT_WAID: str
    VERSION: str
    PHONE_NUMBER_ID: str
    VERIFY_TOKEN: str
    OPENAI_API_KEY: Optional[str] = None
    DB_HOST : str
    DB_PORT : str
    DB_NAME : str
    DB_USER : str
    DB_PASSWORD : str
    class Config:
        env_file = ".env"
        case_sensitive = True

@lru_cache()
def load_configurations():
    """Load and cache configuration settings"""
    load_dotenv(override=True)
    return Settings()

def configure_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        stream=sys.stdout,
    )
