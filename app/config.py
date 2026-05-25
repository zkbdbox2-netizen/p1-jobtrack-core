from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables (or .env file).

    pydantic-settings reads these from the environment automatically.
    If a required field (no default) is missing, the app crashes at startup
    with a clear error — far better than a mysterious failure at runtime.

    Usage anywhere in the app:
        from app.config import settings
        print(settings.database_url)
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",       # silently ignore unknown env vars (don't crash on them)
        # env_file is read on your local machine (outside Docker).
        # Inside the container, Docker Compose injects vars directly into the
        # environment — pydantic-settings reads those fine without needing the file.
    )

    # --- Application ---
    app_name: str = "JobTrack Core"
    environment: str = "development"
    debug: bool = False

    # --- Database ---
    # Required — no default. Must be set in .env or environment.
    # Format: postgresql+asyncpg://user:password@host:port/dbname
    # asyncpg is the async driver; SQLAlchemy uses it under the hood.
    database_url: str

    # --- Redis ---
    redis_url: str = "redis://redis:6379"

    # --- Auth ---
    # Required — no default. Generate with: openssl rand -hex 32
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 15    # short-lived: 15 minutes
    refresh_token_expire_days: int = 7       # long-lived: 7 days


# Module-level singleton — import this everywhere instead of instantiating Settings each time.
settings = Settings()
