"""Validated environment settings. Secret values are never logged."""

from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[1] / ".env",
        extra="ignore",
        hide_input_in_errors=True,
    )
    app_env: Literal["development", "production", "test"] = "development"
    mongodb_uri: SecretStr = SecretStr("mongodb://127.0.0.1:27017")
    mongodb_database: str = "agentshield_ai"
    mongodb_timeout_ms: int = Field(default=3000, ge=100, le=10000)
    mongodb_max_pool_size: int = Field(default=10, ge=1, le=25)
    jwt_secret: SecretStr
    jwt_issuer: str = Field(default="agentshield-api", min_length=1)
    jwt_audience: str = Field(default="agentshield-web", min_length=1)
    access_token_minutes: int = Field(default=15, ge=1, le=30)
    cors_origins: str = "http://localhost:3000"
    login_email_limit: int = Field(default=5, ge=1, le=100)
    login_ip_limit: int = Field(default=30, ge=1, le=1000)
    register_ip_limit: int = Field(default=10, ge=1, le=100)
    rate_window_seconds: int = Field(default=300, ge=10, le=3600)

    @field_validator("jwt_secret")
    @classmethod
    def strong_signing_key(cls, value: SecretStr) -> SecretStr:
        key = value.get_secret_value()
        if len(key.encode()) < 32 or len(set(key)) < 12:
            raise ValueError(
                "JWT_SECRET must be a randomly generated key of at least 32 bytes"
            )
        return value

    @field_validator("mongodb_database")
    @classmethod
    def database_name(cls, value: str) -> str:
        if not value or not all(c.isalnum() or c == "_" for c in value):
            raise ValueError("Invalid database name")
        return value

    @property
    def origins(self) -> list[str]:
        return [v.strip() for v in self.cors_origins.split(",") if v.strip()]

    @property
    def secure_cookies(self) -> bool:
        return self.app_env == "production"

    @property
    def session_cookie(self) -> str:
        return (
            "__Host-agentshield_session"
            if self.secure_cookies
            else "agentshield_session"
        )

    @property
    def csrf_cookie(self) -> str:
        return "__Host-agentshield_csrf" if self.secure_cookies else "agentshield_csrf"

    @model_validator(mode="after")
    def safe_origins(self):
        if not self.origins:
            raise ValueError("At least one exact frontend origin is required")
        for origin in self.origins:
            parsed = urlparse(origin)
            if (
                parsed.scheme not in ("http", "https")
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.path
                or parsed.query
                or parsed.fragment
                or "*" in origin
            ):
                raise ValueError(
                    "CORS_ORIGINS must contain exact HTTP(S) origins without paths"
                )
            if self.secure_cookies and parsed.scheme != "https":
                raise ValueError("Production origins must use HTTPS")
        return self
