import os
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


DEVELOPMENT_SECRET_KEY = "cscl-pharma-super-secret-key-2026-production-ready-jwt"


class Settings(BaseSettings):
    APP_NAME: str = "CSCL DCR System"
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/cscl_dcr_db"
    SECRET_KEY: str = "cscl-pharma-super-secret-key-2026-production-ready-jwt"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440
    DEBUG: bool = False
    APP_ENV: str = Field(
        default_factory=lambda: "production" if os.environ.get("VERCEL") == "1" else "development"
    )

    @model_validator(mode="after")
    def validate_production_settings(self):
        if self.APP_ENV.lower() == "production":
            if (
                not os.environ.get("SECRET_KEY")
                or self.SECRET_KEY == DEVELOPMENT_SECRET_KEY
                or len(self.SECRET_KEY) < 32
            ):
                raise ValueError("A unique SECRET_KEY of at least 32 characters is required in production.")
            if (
                not os.environ.get("DATABASE_URL")
                or not self.DATABASE_URL.startswith(("postgresql://", "postgresql+"))
            ):
                raise ValueError("DATABASE_URL must point to PostgreSQL in the production environment.")
        return self

    @property
    def secure_cookies(self) -> bool:
        return self.APP_ENV.lower() == "production"

    @property
    def debug_enabled(self) -> bool:
        return self.DEBUG and not self.secure_cookies

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()
