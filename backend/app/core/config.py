"""Application settings, loaded from environment variables and a local ``.env`` file."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for the API.

    Every field is overridable through an environment variable of the same name
    (case-insensitive), e.g. ``APP_NAME`` or ``DATABASE_URL``.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Application -----------------------------------------------------
    app_name: str = Field(default="HerMediSafe API", description="Service name.")
    app_version: str = Field(default="0.1.0", description="Service version.")
    environment: str = Field(
        default="local", description="Deployment environment name."
    )
    debug: bool = Field(
        default=False, description="Enable debug logging and extra detail."
    )

    # --- Database --------------------------------------------------------
    database_url: str = Field(
        default="postgresql+asyncpg://hermedisafe:hermedisafe@localhost:5432/hermedisafe",
        description="Async SQLAlchemy connection string (postgresql+asyncpg://...).",
    )
    db_echo: bool = Field(default=False, description="Log every emitted SQL statement.")
    db_pool_size: int = Field(
        default=5, description="Connections kept open per process."
    )
    db_max_overflow: int = Field(
        default=10, description="Extra connections allowed under load."
    )
    db_pool_timeout: int = Field(
        default=30, description="Seconds to wait for a pooled connection."
    )
    db_pool_recycle: int = Field(
        default=1800, description="Recycle connections after N seconds."
    )
    db_health_timeout: float = Field(
        # A cold connect (DNS + TCP + auth) measured ~0.9s locally, so 2s left
        # almost no headroom and risked a false "degraded" at container start.
        # After the startup probe the pool is warm and this returns in ~20ms.
        default=5.0,
        description="Seconds to wait for the database health probe.",
    )

    # --- CORS ------------------------------------------------------------
    cors_origins: list[str] = Field(
        default=["*"],
        description='Allowed origins. JSON list, e.g. CORS_ORIGINS=["*"].',
    )
    # Browsers reject `Access-Control-Allow-Origin: *` together with credentials,
    # so this stays False while we allow every origin. Flip it on only when
    # cors_origins is narrowed to explicit hosts.
    cors_allow_credentials: bool = Field(
        default=False, description="Send cookies/auth headers on cross-origin requests."
    )

    # --- Security / JWT --------------------------------------------------
    # Hackathon defaults. The dev secret is intentionally obvious so that a
    # forgotten SECRET_KEY in production is loud rather than silent -- main.py
    # logs a warning when it is still in use.
    secret_key: str = Field(
        default="dev-insecure-change-me",
        min_length=16,
        description="HMAC secret used to sign JWTs. CHANGE THIS in production.",
    )
    jwt_algorithm: str = Field(
        default="HS256", description="JWT signing algorithm (HS256/HS384/HS512)."
    )
    jwt_issuer: str = Field(
        default="hermedisafe-api",
        description="Value written to and checked in the `iss` claim.",
    )
    access_token_expire_minutes: int = Field(
        # 24h, per the "hackathon simplicity" brief. Long enough that a user is
        # not asked to sign in mid-demo, short enough that a leaked token dies
        # the next day. No refresh tokens yet: logout is client-side only.
        default=60 * 24,
        gt=0,
        description="Access-token lifetime in minutes.",
    )
    bcrypt_rounds: int = Field(
        default=12,
        ge=4,
        le=16,
        description="bcrypt cost factor. Raise to slow offline cracking at CPU cost.",
    )
    max_password_length: int = Field(
        # bcrypt silently ignores everything past 72 *bytes*, so an uncapped
        # field would let two different long passwords hash to the same value.
        # 72 chars is the safe ceiling and is enforced in the signup schema.
        default=72,
        description="Hard cap on password length, in characters.",
    )

    # --- File storage ------------------------------------------------------
    storage_root: Path = Field(
        # Resolved against the process working directory. Under `docker compose`
        # that is /app, and the Dockerfile puts this on a volume so uploads
        # survive a container rebuild.
        default=Path("storage"),
        description="Directory holding uploaded prescription files.",
    )
    storage_url_prefix: str = Field(
        # Must match the StaticFiles mount in main.create_app().
        default="/files",
        description="URL prefix the local storage backend serves files from.",
    )
    max_upload_bytes: int = Field(
        # 10 MiB, per the spec. Enforced while streaming the upload in
        # app/services/prescriptions.py, not by trusting Content-Length, which
        # the client also controls.
        default=10 * 1024 * 1024,
        gt=0,
        description="Hard cap on prescription upload size in bytes.",
    )


@lru_cache
def get_settings() -> Settings:
    """Return a cached ``Settings`` instance so the ``.env`` file is read once."""
    return Settings()
