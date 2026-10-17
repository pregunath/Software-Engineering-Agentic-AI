from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="AGENT_", extra="ignore")

    app_name: str = "Forge Software Engineer Agent"
    environment: str = "development"
    database_url: str = "sqlite:///./agent.db"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "gemma4:e2b"
    ollama_timeout_seconds: float = Field(default=30.0, ge=1.0, le=300.0)
    api_host: str = "127.0.0.1"
    api_port: int = Field(default=8000, ge=1, le=65535)
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    public_base_url: str = "http://127.0.0.1:8000"
    api_key: str = ""
    # When true, the API may register absolute paths on the host running Forge.
    # Keep false on public cloud hosts so clients cannot probe the server filesystem.
    allow_host_workspaces: bool = True

    @field_validator("cors_origins", mode="before")
    @classmethod
    def normalize_cors_origins(cls, value: object) -> str:
        if value is None:
            return "http://localhost:3000,http://127.0.0.1:3000"
        return str(value)

    def cors_origin_list(self) -> list[str]:
        origins = [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]
        return origins or ["http://localhost:3000", "http://127.0.0.1:3000"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
