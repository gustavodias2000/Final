"""Configuração de execução carregada exclusivamente do ambiente."""

import os
from dataclasses import dataclass


class ConfigurationError(RuntimeError):
    """A aplicação não possui configuração segura para iniciar."""


def _origins_from_env(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(origin.strip().rstrip("/") for origin in value.split(",") if origin.strip())


def _bool_from_env(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    project_name: str
    environment: str
    secret_key: str
    database_url: str
    cors_origins: tuple[str, ...]
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    siscomex_ncm_url: str = "https://portalunico.siscomex.gov.br/classif/api/publico/nomenclatura/download/json"
    cest_lookup_url_template: str = "https://codigocest.com.br/index.php?ncm={ncm}"
    cest_lookup_enabled: bool = False
    cest_lookup_max_unique_ncms: int = 250
    external_reference_lookup_enabled: bool = False
    external_reference_lookup_max_unique_ncms: int = 100
    external_reference_retry_seconds: int = 70
    external_reference_full_retry_seconds: int = 120
    external_reference_max_cycles: int = 3
    tabelas_fiscais_api_base_url: str = "https://tabelasfiscais.com.br/api/v1"
    ncm_api_base_url: str = "https://apincm-kb2xbt7jka-rj.a.run.app/v1"
    ncm_api_key: str = ""
    external_request_timeout_seconds: float = 15.0
    cest_cache_ttl_seconds: int = 86_400
    cest_candidate_score_threshold: float = 85.0
    cest_candidate_score_margin: float = 12.0
    max_upload_bytes: int = 10 * 1024 * 1024
    audit_worker_poll_interval_seconds: float = 2.0
    audit_worker_lease_seconds: int = 120
    audit_worker_max_attempts: int = 3
    audit_worker_progress_batch_size: int = 100

    @classmethod
    def from_environment(cls) -> "Settings":
        return cls(
            project_name=os.getenv("PROJECT_NAME", "Auditor NCM SaaS"),
            environment=os.getenv("ENVIRONMENT", "development").lower(),
            secret_key=os.getenv("SECRET_KEY", ""),
            database_url=os.getenv("DATABASE_URL", ""),
            cors_origins=_origins_from_env(os.getenv("CORS_ORIGINS")),
            access_token_expire_minutes=int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60")),
            siscomex_ncm_url=os.getenv(
                "SISCOMEX_NCM_URL",
                "https://portalunico.siscomex.gov.br/classif/api/publico/nomenclatura/download/json",
            ),
            cest_lookup_url_template=os.getenv(
                "CEST_LOOKUP_URL_TEMPLATE",
                "https://codigocest.com.br/index.php?ncm={ncm}",
            ),
            cest_lookup_enabled=_bool_from_env(os.getenv("CEST_LOOKUP_ENABLED")),
            cest_lookup_max_unique_ncms=int(os.getenv("CEST_LOOKUP_MAX_UNIQUE_NCMS", "250")),
            external_reference_lookup_enabled=_bool_from_env(
                os.getenv("EXTERNAL_REFERENCE_LOOKUP_ENABLED")
            ),
            external_reference_lookup_max_unique_ncms=int(
                os.getenv("EXTERNAL_REFERENCE_LOOKUP_MAX_UNIQUE_NCMS", "100")
            ),
            external_reference_retry_seconds=int(os.getenv("EXTERNAL_REFERENCE_RETRY_SECONDS", "70")),
            external_reference_full_retry_seconds=int(
                os.getenv("EXTERNAL_REFERENCE_FULL_RETRY_SECONDS", "120")
            ),
            external_reference_max_cycles=int(os.getenv("EXTERNAL_REFERENCE_MAX_CYCLES", "3")),
            tabelas_fiscais_api_base_url=os.getenv(
                "TABELAS_FISCAIS_API_BASE_URL", "https://tabelasfiscais.com.br/api/v1"
            ).rstrip("/"),
            ncm_api_base_url=os.getenv(
                "NCM_API_BASE_URL", "https://apincm-kb2xbt7jka-rj.a.run.app/v1"
            ).rstrip("/"),
            ncm_api_key=os.getenv("NCM_API_KEY", ""),
            external_request_timeout_seconds=float(os.getenv("EXTERNAL_REQUEST_TIMEOUT_SECONDS", "15")),
            cest_cache_ttl_seconds=int(os.getenv("CEST_CACHE_TTL_SECONDS", "86400")),
            cest_candidate_score_threshold=float(os.getenv("CEST_CANDIDATE_SCORE_THRESHOLD", "85")),
            cest_candidate_score_margin=float(os.getenv("CEST_CANDIDATE_SCORE_MARGIN", "12")),
            max_upload_bytes=int(os.getenv("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024))),
            audit_worker_poll_interval_seconds=float(os.getenv("AUDIT_WORKER_POLL_INTERVAL_SECONDS", "2")),
            audit_worker_lease_seconds=int(os.getenv("AUDIT_WORKER_LEASE_SECONDS", "120")),
            audit_worker_max_attempts=int(os.getenv("AUDIT_WORKER_MAX_ATTEMPTS", "3")),
            audit_worker_progress_batch_size=int(os.getenv("AUDIT_WORKER_PROGRESS_BATCH_SIZE", "100")),
        )

    def validate(self) -> None:
        missing = [
            name
            for name, value in (
                ("SECRET_KEY", self.secret_key),
                ("DATABASE_URL", self.database_url),
                ("CORS_ORIGINS", ",".join(self.cors_origins)),
            )
            if not value
        ]

        if missing:
            raise ConfigurationError(
                "Configuração ausente: " + ", ".join(missing) + ". Consulte .env.example."
            )

        if "*" in self.cors_origins:
            raise ConfigurationError("CORS_ORIGINS não pode conter '*'.")

        if self.access_token_expire_minutes <= 0:
            raise ConfigurationError("ACCESS_TOKEN_EXPIRE_MINUTES deve ser maior que zero.")

        if self.external_request_timeout_seconds <= 0:
            raise ConfigurationError("EXTERNAL_REQUEST_TIMEOUT_SECONDS deve ser maior que zero.")

        if self.cest_cache_ttl_seconds <= 0:
            raise ConfigurationError("CEST_CACHE_TTL_SECONDS deve ser maior que zero.")

        if not 0 <= self.cest_candidate_score_threshold <= 100:
            raise ConfigurationError("CEST_CANDIDATE_SCORE_THRESHOLD deve estar entre 0 e 100.")

        if self.cest_candidate_score_margin < 0:
            raise ConfigurationError("CEST_CANDIDATE_SCORE_MARGIN não pode ser negativo.")

        if self.cest_lookup_max_unique_ncms <= 0:
            raise ConfigurationError("CEST_LOOKUP_MAX_UNIQUE_NCMS deve ser maior que zero.")

        if self.external_reference_lookup_max_unique_ncms <= 0:
            raise ConfigurationError("EXTERNAL_REFERENCE_LOOKUP_MAX_UNIQUE_NCMS deve ser maior que zero.")

        if self.external_reference_retry_seconds <= 0:
            raise ConfigurationError("EXTERNAL_REFERENCE_RETRY_SECONDS deve ser maior que zero.")

        if self.external_reference_full_retry_seconds <= 0:
            raise ConfigurationError("EXTERNAL_REFERENCE_FULL_RETRY_SECONDS deve ser maior que zero.")

        if self.external_reference_max_cycles <= 0:
            raise ConfigurationError("EXTERNAL_REFERENCE_MAX_CYCLES deve ser maior que zero.")

        if "{ncm}" not in self.cest_lookup_url_template:
            raise ConfigurationError("CEST_LOOKUP_URL_TEMPLATE deve conter o placeholder {ncm}.")

        if self.max_upload_bytes <= 0:
            raise ConfigurationError("MAX_UPLOAD_BYTES deve ser maior que zero.")

        if self.audit_worker_poll_interval_seconds <= 0:
            raise ConfigurationError("AUDIT_WORKER_POLL_INTERVAL_SECONDS deve ser maior que zero.")

        if self.audit_worker_lease_seconds <= 0:
            raise ConfigurationError("AUDIT_WORKER_LEASE_SECONDS deve ser maior que zero.")

        if self.audit_worker_max_attempts <= 0:
            raise ConfigurationError("AUDIT_WORKER_MAX_ATTEMPTS deve ser maior que zero.")

        if self.audit_worker_progress_batch_size <= 0:
            raise ConfigurationError("AUDIT_WORKER_PROGRESS_BATCH_SIZE deve ser maior que zero.")


settings = Settings.from_environment()


