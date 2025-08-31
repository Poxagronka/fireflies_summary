"""Configuration module for Fireflies Summary Bot."""

import os
from dotenv import load_dotenv
from typing import Optional

load_dotenv()


class Config:
    """Application configuration."""
    
    # API Keys
    FIREFLIES_API_KEY: str = os.getenv("FIREFLIES_API_KEY", "")
    SLACK_BOT_TOKEN: str = os.getenv("SLACK_BOT_TOKEN", "")
    SLACK_SIGNING_SECRET: str = os.getenv("SLACK_SIGNING_SECRET", "")
    SLACK_CLIENT_SECRET: str = os.getenv("SLACK_CLIENT_SECRET", "")
    
    # Notification settings
    NOTIFICATION_MINUTES_BEFORE: int = int(os.getenv("NOTIFICATION_MINUTES_BEFORE", "30"))
    CHECK_INTERVAL_MINUTES: int = int(os.getenv("CHECK_INTERVAL_MINUTES", "5"))
    
    # Logging
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    
    # Database
    REDIS_URL: Optional[str] = os.getenv("REDIS_URL")
    DATABASE_URL: Optional[str] = os.getenv("DATABASE_URL")
    
    # Fireflies API
    FIREFLIES_API_URL: str = "https://api.fireflies.ai/graphql"
    
    # Server settings
    PORT: int = int(os.getenv("PORT", "8080"))
    HOST: str = os.getenv("HOST", "0.0.0.0")
    
    # Google Calendar
    GOOGLE_CALENDAR_CREDENTIALS: Optional[str] = os.getenv("GOOGLE_CALENDAR_CREDENTIALS")
    
    @classmethod
    def validate(cls) -> None:
        """Validate required configuration."""
        required_fields = [
            "FIREFLIES_API_KEY",
            "SLACK_BOT_TOKEN",
            "SLACK_SIGNING_SECRET"
        ]
        
        missing = []
        for field in required_fields:
            if not getattr(cls, field):
                missing.append(field)
        
        if missing:
            raise ValueError(f"Missing required configuration: {', '.join(missing)}")


config = Config()