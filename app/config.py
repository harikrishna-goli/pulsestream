from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class Settings(BaseSettings):
    PROJECT_NAME: str = "PulseStream"
    API_V1_PREFIX: str = "/api/v1"
    DATABASE_URL: str = "postgresql+asyncpg://user:password@localhost:5432/pulsestream"
    REDIS_URL: Optional[str] = "redis://localhost:6379/0"
    RATE_LIMIT_PER_MINUTE: int = 60
    WEBHOOK_SECRET_KEY: str = "super-secret-hmac-key"
    #Configuration for the rate limiting Fail-open
    RATE_LIMIT_FAIL_OPEN: bool = True
    REDIS_TIMEOUT_SECONDS: float = 0.1 #100 milliseconds
    
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
