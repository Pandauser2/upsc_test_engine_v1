"""
Application configuration from environment variables.
See .env.example for required keys.
"""
from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Load and validate config from env."""

    # Database
    database_url: str = "postgresql://user:password@localhost:5432/upsc_test_engine"

    # JWT (used from Step 3)
    secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_hours: int = 24

    # LLM (used from Step 6)
    llm_provider: str = "openai"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    prompt_version: str = "mcq_v1"
    max_generation_time_seconds: int = 300

    # File uploads
    upload_dir: Path = Path("./uploads")

    # CORS: comma-separated origins, e.g. http://localhost:3000,https://app.example.com
    cors_origins: str = "http://localhost:3000"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
