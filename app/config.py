import base64
import hashlib
from functools import lru_cache
from urllib.parse import urlparse

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    environment: str = "local"
    database_url: str = "postgresql://homebase:homebase@localhost:5432/homebase"
    secret_key: str = "dev-secret-key-change-in-production"
    debug: bool = False
    base_url: str = "http://localhost:8000"
    allowed_hosts: str | None = None
    upload_dir: str = "./uploads"
    admin_username: str = "admin"
    admin_password: str = "changeme"
    session_max_age: int = 604800  # 7 days in seconds
    cookie_secure: bool | None = None
    csrf_enabled: bool | None = None
    login_rate_limit_attempts: int = 5
    login_rate_limit_window_seconds: int = 900
    resend_api_key: str | None = None
    email_from: str = "homebase@example.com"
    email_enabled: bool = False
    log_level: str = "INFO"
    log_format: str = "plain"
    log_sql: bool = False
    totp_encryption_key: str | None = None

    @property
    def is_production(self) -> bool:
        return self.environment == "production" or not self.debug

    @property
    def effective_cookie_secure(self) -> bool:
        return self.cookie_secure if self.cookie_secure is not None else self.is_production

    @property
    def effective_csrf_enabled(self) -> bool:
        return self.csrf_enabled if self.csrf_enabled is not None else self.is_production

    @property
    def email_configured(self) -> bool:
        return self.email_enabled and bool(self.resend_api_key)

    @property
    def effective_allowed_hosts(self) -> list[str]:
        if self.allowed_hosts:
            return [host.strip() for host in self.allowed_hosts.split(",") if host.strip()]
        if self.is_production:
            parsed = urlparse(self.base_url)
            return [parsed.hostname] if parsed.hostname else []
        return ["*"]

    @property
    def effective_totp_encryption_key(self) -> str:
        if self.totp_encryption_key:
            return self.totp_encryption_key
        digest = hashlib.sha256(self.secret_key.encode()).digest()
        return base64.urlsafe_b64encode(digest).decode()


@lru_cache
def get_settings() -> Settings:
    return Settings()
