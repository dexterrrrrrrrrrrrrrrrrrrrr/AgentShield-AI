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

    groq_api_key: SecretStr = SecretStr("")
    groq_model: str = Field(
        default="llama-3.1-8b-instant", min_length=1, max_length=100
    )
    ollama_enabled: bool = False
    ollama_model: str = "qwen2.5:1.5b"
    ollama_url: str = "http://127.0.0.1:11434"
    agent_provider_timeout: float = Field(default=15, ge=0.1, le=60)
    agent_request_timeout: float = Field(default=45, ge=0.1, le=90)
    agent_max_iterations: int = Field(default=4, ge=1, le=6)
    agent_max_tool_calls: int = Field(default=3, ge=0, le=5)
    agent_user_limit: int = Field(default=10, ge=1, le=100)

    monitor_send_timeout: float = Field(default=3, ge=0.05, le=5)
    monitor_heartbeat_seconds: float = Field(default=15, ge=1, le=30)
    monitor_pong_seconds: float = Field(default=35, ge=3, le=90)
    monitor_poll_seconds: float = Field(default=1, ge=0.05, le=5)
    sandbox_enabled: bool = False
    sandbox_policy: Literal["deny", "approval", "allow"] = "approval"
    sandbox_docker_url: str = "unix:///var/run/docker.sock"
    sandbox_memory_mb: int = Field(default=128, ge=128, le=256)
    sandbox_cpus: float = Field(default=1, ge=0.1, le=1)
    sandbox_pids: int = Field(default=32, ge=8, le=64)
    sandbox_timeout: int = Field(default=10, ge=1, le=15)
    sandbox_output_bytes: int = Field(default=65536, ge=1024, le=65536)
    sandbox_code_bytes: int = Field(default=32768, ge=1024, le=32768)
    sandbox_retention_days: int = Field(default=7, ge=1, le=30)
    sandbox_approval_seconds: int = Field(default=300, ge=30, le=600)
    sandbox_user_limit: int = Field(default=5, ge=1, le=20)

    @field_validator("sandbox_docker_url")
    @classmethod
    def local_docker(cls, value):
        if not value.startswith("unix:///"):
            raise ValueError("Only a local Unix Docker socket is permitted")
        return value

    @field_validator("ollama_url")
    @classmethod
    def local_ollama(cls, value):
        p = urlparse(value)
        if (
            p.scheme != "http"
            or p.hostname not in ("localhost", "127.0.0.1", "::1")
            or p.username
            or p.password
            or p.path not in ("", "/")
            or p.query
            or p.fragment
        ):
            raise ValueError("Ollama URL must be an HTTP loopback origin")
        return value

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
    def monitoring_timing(self):
        if (
            self.monitor_pong_seconds
            <= self.monitor_heartbeat_seconds + self.monitor_poll_seconds
        ):
            raise ValueError(
                "Monitor pong timeout must exceed heartbeat plus polling interval"
            )
        return self

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
