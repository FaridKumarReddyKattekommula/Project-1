from datetime import datetime
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Runtime configuration. Every field can be overridden with an env var
    prefixed CIRCLES_, e.g. CIRCLES_DATABASE_PATH=/tmp/circles.db."""

    model_config = SettingsConfigDict(env_prefix="CIRCLES_", env_file=".env", extra="ignore")

    database_path: Path = ROOT / "var" / "circles.db"
    data_dir: Path = ROOT / "data"
    # Build the database from data_dir on startup if it doesn't exist yet.
    auto_seed: bool = True

    # Reference "now" for recency maths. The seed data is a frozen snapshot, so
    # measuring against the wall clock would make every Circle look staler each
    # day. When unset we use the most recent activity timestamp in the database.
    as_of: datetime | None = None

    default_limit: int = Field(default=5, ge=1)
    max_limit: int = Field(default=20, ge=1)

    log_level: str = "INFO"
    log_json: bool = False
    cors_origins: list[str] = []


@lru_cache
def get_settings() -> Settings:
    return Settings()
