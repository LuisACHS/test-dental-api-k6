"""Configuracion central, leida de variables de entorno / .env."""

from __future__ import annotations

from functools import lru_cache
from urllib.parse import quote_plus
from zoneinfo import ZoneInfo

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- App ---------------------------------------------------------------
    app_name: str = "Dental Booking API"
    app_env: str = "dev"
    api_v1_prefix: str = "/api/v1"

    # --- Base de datos -----------------------------------------------------
    postgres_user: str = "dental"
    postgres_password: str = "dental"
    postgres_db: str = "dental"
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    #  Si viene definida gana sobre las cinco de arriba.
    database_url: str | None = None
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_echo: bool = False

    # --- Autenticacion -----------------------------------------------------
    secret_key: str = "dev-secret-change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    #  bcrypt es CPU-bound a proposito: con 12 rondas un login cuesta ~250 ms y
    #  domina la medicion del endpoint. Bajarlo al hacer pruebas de carga.
    bcrypt_rounds: int = Field(default=12, ge=4, le=16)

    admin_token: str = "dev-admin-token-change-me"
    bootstrap_admin_email: str | None = None
    bootstrap_admin_password: str | None = None

    # --- Reglas de negocio -------------------------------------------------
    min_appointment_minutes: int = Field(default=15, ge=1)
    max_appointment_minutes: int = Field(default=240, ge=1)
    allow_past_appointments: bool = False

    #  Horario de atencion de la clinica, en SU zona horaria local. La API
    #  sigue hablando en UTC hacia afuera; esto solo define desde y hasta que
    #  hora se generan huecos.
    clinic_timezone: str = "America/Santiago"
    clinic_open_hour: int = Field(default=9, ge=0, le=23)
    clinic_close_hour: int = Field(default=18, ge=1, le=24)
    default_slot_minutes: int = Field(default=30, ge=5, le=480)

    # --- Observabilidad ----------------------------------------------------
    metrics_enabled: bool = True

    # --- Caos --------------------------------------------------------------
    #  Solo el estado INICIAL; se modifica en caliente por /admin/chaos.
    chaos_enabled: bool = False
    chaos_latency_ms: int = Field(default=0, ge=0, le=60_000)
    chaos_latency_jitter_ms: int = Field(default=0, ge=0, le=60_000)
    chaos_error_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    chaos_error_status: int = Field(default=503, ge=400, le=599)
    #  String y no list[str] a proposito: pydantic-settings intenta parsear como
    #  JSON cualquier campo de tipo complejo, y "*" no es JSON valido.
    chaos_routes: str = "*"

    @model_validator(mode="after")
    def _check_clinic_hours(self) -> "Settings":
        #  Falla al arrancar y no en el primer request: una config imposible
        #  tiene que ser evidente de inmediato.
        if self.clinic_close_hour <= self.clinic_open_hour:
            raise ValueError("CLINIC_CLOSE_HOUR debe ser mayor que CLINIC_OPEN_HOUR")
        try:
            ZoneInfo(self.clinic_timezone)
        except Exception as exc:
            raise ValueError(f"CLINIC_TIMEZONE invalida: {self.clinic_timezone}") from exc
        return self

    @property
    def clinic_tz(self) -> ZoneInfo:
        #  ZoneInfo cachea internamente por nombre: la propiedad no cuesta.
        return ZoneInfo(self.clinic_timezone)

    @property
    def sqlalchemy_url(self) -> str:
        if self.database_url:
            return self.database_url
        return (
            "postgresql+asyncpg://"
            f"{quote_plus(self.postgres_user)}:{quote_plus(self.postgres_password)}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def chaos_route_patterns(self) -> list[str]:
        return [p.strip() for p in self.chaos_routes.split(",") if p.strip()] or ["*"]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
