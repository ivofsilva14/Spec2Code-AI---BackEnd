"""Ponto de entrada da API FastAPI do TCC IA."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core import settings
from app.api.routes.datasets import router as datasets_router
from app.api.routes.generation import router as generation_router

app = FastAPI(
    title=settings.app_name,
    description=(
        "API local para orquestrar a geração de software por agentes de IA. "
        "Os datasets enviados são validados e armazenados no workspace local."
    ),
    version=settings.app_version,
)

# Em produção, restrinja CORS_ORIGINS aos domínios realmente utilizados.
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/", tags=["health"], summary="Informações básicas da API")
def root() -> dict[str, str]:
    """Confirma que a API está respondendo e informa sua versão."""
    return {
        "application": settings.app_name,
        "version": settings.app_version,
        "status": "running",
        "docs": "/docs",
    }


@app.get("/api/health", tags=["health"], summary="Verificação de saúde")
def health_check() -> dict[str, str]:
    """Endpoint simples para verificar disponibilidade da API."""
    return {"status": "ok"}


# Rotas da API
app.include_router(datasets_router)

app.include_router(generation_router)
