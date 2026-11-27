from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"

load_dotenv(dotenv_path=ENV_PATH)


class Settings(BaseSettings):
    # SQLite only: database.py runs SQLite PRAGMA statements for its lightweight migration.
    database_url: str = "sqlite:///./app.db"

    # Sentry: DSN reports this backend's own errors; the secret verifies incoming webhooks.
    sentry_dsn: str | None = None
    sentry_webhook_secret: str | None = None

    # Defaults to the address derived from the investigation agent's seed (see addresses.py).
    investigation_agent_address: str | None = None

    default_repo_full_name: str | None = None
    default_branch: str = "main"

    github_token: str | None = None

    asi_one_api_key: str | None = None
    asi_one_base_url: str = "https://api.asi1.ai/v1"
    asi_one_model: str = "asi1"

    model_config = SettingsConfigDict(
        env_file=str(ENV_PATH),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


settings = Settings()
