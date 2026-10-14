"""Configuração centralizada da API e do motor multiagente.

As variáveis são lidas do ambiente. Durante o desenvolvimento, o arquivo
``.env`` localizado na raiz do backend é carregado automaticamente.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

# app/core/config.py -> core -> app -> raiz do backend
PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT_ROOT / ".env"

# Não sobrescreve variáveis que já foram definidas no ambiente do sistema.
load_dotenv(dotenv_path=ENV_FILE, override=False)


def _env_int(name: str, default: int, *, minimum: int = 1) -> int:
    """Lê uma variável inteira e informa claramente quando ela é inválida."""
    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        return default
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"A variável {name} deve ser um número inteiro.") from exc
    if value < minimum:
        raise ValueError(f"A variável {name} deve ser maior ou igual a {minimum}.")
    return value


def _resolve_path(raw_path: str, default: Path) -> Path:
    """Resolve caminhos relativos a partir da raiz do backend."""
    candidate = Path(raw_path).expanduser() if raw_path.strip() else default
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    return candidate.resolve()


@dataclass(frozen=True, slots=True)
class Settings:
    """Configurações imutáveis usadas pela API e pelo pipeline."""

    app_name: str
    app_version: str
    environment: str
    gemini_api_key: str | None
    gemini_model_name: str
    workspace_dir: Path
    cors_origins: tuple[str, ...]
    max_upload_size_mb: int
    job_timeout_seconds: int

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024


def _build_settings() -> Settings:
    default_workspace = PROJECT_ROOT / "workspace"
    raw_origins = os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    )
    cors_origins = tuple(
        origin.strip().rstrip("/")
        for origin in raw_origins.split(",")
        if origin.strip()
    )

    api_key = os.getenv("GEMINI_API_KEY", "").strip() or None

    return Settings(
        app_name=os.getenv("APP_NAME", "TCC IA - Gerador de Sistemas Multiagente").strip(),
        app_version=os.getenv("APP_VERSION", "0.1.0").strip(),
        environment=os.getenv("APP_ENV", "development").strip().lower(),
        gemini_api_key=api_key,
        gemini_model_name=os.getenv("GEMINI_MODEL_NAME", "gemini-3.5-flash-lite").strip(),
        workspace_dir=_resolve_path(os.getenv("WORKSPACE_DIR", "workspace"), default_workspace),
        cors_origins=cors_origins,
        max_upload_size_mb=_env_int("MAX_UPLOAD_SIZE_MB", 25),
        job_timeout_seconds=_env_int("JOB_TIMEOUT_SECONDS", 1800),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Retorna uma instância cacheada das configurações.

    Para recarregar após alterar variáveis durante testes, use
    ``get_settings.cache_clear()``.
    """
    return _build_settings()


# Instância conveniente para os módulos da aplicação.
settings = get_settings()
