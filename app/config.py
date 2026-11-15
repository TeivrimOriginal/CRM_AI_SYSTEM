# ===== app/config.py =====
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str = "postgresql+psycopg://crm:crm@db:5432/crm"
    ENVIRONMENT: str = "local"  # local|production

    JWT_SECRET: str = "change-me-in-production"
    JWT_ALG: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 720

    APP_TZ: str = "Europe/Moscow"

    # Cookie сессии: в продакшене включается COOKIE_SECURE=true (HTTPS обязателен)
    COOKIE_SECURE: bool = False
    COOKIE_SAMESITE: str = "lax"

    # PENDING_DECISION: решается владельцем до запуска
    SALE_CONFIRMATION_CRITERION: str = ""  # manual|contract_signed|prepayment|custom|""
    BELARUS_CHECK_REQUIRED_BEFORE: str = "proposal_sent"  # proposal_sent|handoff|none
    BELARUS_CHECKER_ROLE: str = "manager"  # manager|supervisor

    BOOTSTRAP_SUPERVISOR_EMAIL: str = "supervisor@example.com"
    BOOTSTRAP_SUPERVISOR_PASSWORD: str = "ChangeMe123!"

    # Импорт
    IMPORT_PREVIEW_TTL_MINUTES: int = 120
    MAX_IMPORT_ROWS: int = 5000

    # Простая защита от перебора пароля: N попыток за окно (секунды)
    LOGIN_MAX_ATTEMPTS: int = 10
    LOGIN_WINDOW_SECONDS: int = 300

    # Проверка, что секрет изменён (для продакшена)
    @property
    def jwt_secret_is_default(self) -> bool:
        return self.JWT_SECRET in ("change-me-in-production", "", None)


settings = Settings()
