from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="AGENT_", extra="ignore")

    app_name: str = "Local AI Software Engineer Agent"
    environment: str = "development"
    database_url: str = "sqlite:///./agent.db"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "gemma4:e2b"
    ollama_timeout_seconds: float = Field(default=30.0, ge=1.0, le=300.0)
    api_host: str = "127.0.0.1"
    api_port: int = Field(default=8000, ge=1, le=65535)


@lru_cache
def get_settings() -> Settings:
    return Settings()
