import os
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    """
    Application settings, loaded from environment variables or .env file.
    """
    DATABASE_URL: str = "postgresql://user:password@localhost:5432/alemeno"
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/0"
    GROQ_API_KEY: str = ""
    
    # Application constants
    DOMESTIC_BRANDS: List[str] = ["swiggy", "ola", "irctc", "zomato", "paytm", "bms", "bookmyshow"]
    BATCH_SIZE: int = 20

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

# Global settings instance
settings = Settings()
