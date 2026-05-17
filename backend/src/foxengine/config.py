from functools import lru_cache

from cryptography.fernet import Fernet
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FOX_", env_file=".env", extra="ignore")

    database_url: str = Field(
        default="postgresql+asyncpg://fox:fox@localhost:5432/foxengine",
    )
    clickhouse_host: str = "localhost"
    clickhouse_port: int = 8123
    clickhouse_user: str = "default"
    clickhouse_password: str = ""
    clickhouse_database: str = "foxengine"

    s3_endpoint_url: str = "http://localhost:9000"
    s3_access_key_id: str = "fox"
    s3_secret_access_key: str = "foxfoxfox"
    s3_bucket_uploads: str = "uploads"
    s3_bucket_exports: str = "exports"
    s3_region: str = "us-east-1"

    master_key: str = Field(
        description="Fernet key (urlsafe base64) for encrypting secrets in settings",
    )

    @field_validator("master_key")
    @classmethod
    def validate_master_key(cls, v: str) -> str:
        key = v.strip()
        if not key:
            raise ValueError(
                "FOX_MASTER_KEY is empty; set a Fernet key from "
                "cryptography.fernet.Fernet.generate_key().decode()"
            )
        try:
            Fernet(key.encode())
        except (ValueError, TypeError) as e:
            raise ValueError(
                "FOX_MASTER_KEY must be a valid Fernet key (32 url-safe base64-encoded bytes)"
            ) from e
        return key

    jwt_ttl_hours: int = 12

    max_index_rows_sync: int = 5000

    max_export_rows: int = 5_000_000

    related_rows_cap: int = 1000

    llm_enabled: bool = True
    llm_base_url: str = "http://localhost:8080"
    llm_model: str = "local"
    llm_api_key: str | None = None
    llm_health_path: str = "health"
    llm_timeout_s: float = 30.0
    llm_health_timeout_s: float = 3.0

    @field_validator("database_url", mode="before")
    @classmethod
    def coerce_db_url(cls, v: object) -> object:
        if isinstance(v, str) and v.startswith("postgres://"):
            return v.replace("postgres://", "postgresql+asyncpg://", 1)
        return v

    @property
    def database_url_sync(self) -> str:
        u = str(self.database_url)
        return u.replace("postgresql+asyncpg://", "postgresql://", 1)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # ty: ignore[missing-argument]  # FOX_MASTER_KEY from env / .env via pydantic-settings
