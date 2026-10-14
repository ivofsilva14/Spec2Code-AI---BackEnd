"""Serviço para iniciar e acompanhar execuções do pipeline multiagente."""

from __future__ import annotations

import json
import os
import shutil
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core import settings
from app.services.dataset_service import (
    DatasetServiceError,
    REQUIRED_DATASET_NAMES,
    validate_dataset_payloads,
)

DATASET_FILENAMES = {
    "requisitos_funcionais": "requisitos_funcionais.json",
    "requisitos_nao_funcionais": "requisitos_nao_funcionais.json",
    "regras_negocio": "regras_negocio.json",
    "projetos_interiores": "projetos_interiores.json",
}


class GenerationServiceError(ValueError):
    """Erro de domínio ao iniciar ou executar uma geração."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _jobs_root() -> Path:
    return (settings.workspace_dir / "jobs").resolve()


def get_job_dir(job_id: str) -> Path:
    """Resolve job_id de forma segura, impedindo traversal de diretórios."""
    if not job_id or any(ch not in "0123456789abcdefABCDEF-" for ch in job_id):
        raise GenerationServiceError("job_id inválido.")
    jobs_root = _jobs_root()
    job_dir = (jobs_root / job_id).resolve()
    if jobs_root not in job_dir.parents:
        raise GenerationServiceError("job_id inválido.")
    if not job_dir.is_dir():
        raise FileNotFoundError(f"Execução '{job_id}' não foi encontrada.")
    return job_dir


def _status_path(job_dir: Path) -> Path:
    return job_dir / "job_status.json"


def read_job_status(job_id: str) -> dict[str, Any]:
    job_dir = get_job_dir(job_id)
    status_path = _status_path(job_dir)
    if not status_path.is_file():
        # Execuções criadas pela rota de upload antes da introdução do status persistido.
        return {
            "job_id": job_id,
            "status": "datasets_uploaded",
            "created_at": None,
            "updated_at": None,
            "message": "Datasets recebidos; geração ainda não iniciada.",
        }
    try:
        return json.loads(status_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GenerationServiceError("Não foi possível ler o status desta execução.") from exc


def _write_status(job_dir: Path, payload: dict[str, Any]) -> None:
    payload["updated_at"] = _utc_now()
    temp_path = job_dir / "job_status.json.tmp"
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(_status_path(job_dir))


def _load_local_datasets(job_dir: Path) -> dict[str, dict[str, Any]]:
    datasets_dir = job_dir / "datasets"
    if not datasets_dir.is_dir():
        raise GenerationServiceError("A pasta local de datasets não foi encontrada.")

    parsed: dict[str, Any] = {}
    for logical_name in REQUIRED_DATASET_NAMES:
        path = datasets_dir / DATASET_FILENAMES[logical_name]
        if not path.is_file():
            raise GenerationServiceError(
                f"Dataset obrigatório não encontrado no armazenamento local: {path.name}."
            )
        try:
            parsed[logical_name] = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise GenerationServiceError(f"Não foi possível ler o dataset {path.name}.") from exc

    try:
        return validate_dataset_payloads(parsed)
    except DatasetServiceError as exc:
        raise GenerationServiceError(str(exc)) from exc


def start_generation(job_id: str) -> dict[str, Any]:
    """Marca a execução como running; a rota dispara run_generation em background."""
    job_dir = get_job_dir(job_id)
    current = read_job_status(job_id)
    if current.get("status") == "running":
        raise GenerationServiceError("Esta execução já está em andamento.")
    if current.get("status") == "completed":
        raise GenerationServiceError("Esta execução já foi concluída. Envie os datasets novamente para gerar outra execução.")

    # Verifica os arquivos antes de aceitar o processamento.
    _load_local_datasets(job_dir)
    output_dir = job_dir / "output"
    checkpoint_file = job_dir / ".checkpoints" / "pipeline_state.pkl"
    manifest_file = job_dir / ".checkpoints" / "pipeline_state.json"
    has_checkpoint = checkpoint_file.is_file() and manifest_file.is_file()
    # Jobs com falha podem ser retomados se houver checkpoint. Jobs sem checkpoint
    # e com output parcial continuam protegidos contra sobrescrita acidental.
    if output_dir.exists() and any(output_dir.iterdir()) and not has_checkpoint:
        raise GenerationServiceError(
            "A pasta output já contém arquivos, mas não há checkpoint recuperável. "
            "Envie os datasets novamente para criar um novo job."
        )

    payload = {
        "job_id": job_id,
        "status": "running",
        "created_at": current.get("created_at") or _utc_now(),
        "started_at": _utc_now(),
        "updated_at": _utc_now(),
        "message": "Geração multiagente iniciada; a execução retomará do último checkpoint válido quando disponível.",
        "resume_available": has_checkpoint,
        "output_dir": str(output_dir),
        "result": None,
        "error": None,
    }
    _write_status(job_dir, payload)
    return payload


def run_generation(job_id: str) -> None:
    """Executa o pipeline de forma síncrona; chamado como tarefa de background."""
    job_dir = get_job_dir(job_id)
    status_payload = read_job_status(job_id)
    try:
        datasets = _load_local_datasets(job_dir)
        output_dir = job_dir / "output"
        # Import tardio: a API e suas rotas podem iniciar sem carregar o SDK do LLM.
        from app.engine import executar_pipeline

        result = executar_pipeline(datasets=datasets, output_dir=output_dir, resume=True)
        status_payload.update({
            "status": "completed",
            "message": "Geração concluída.",
            "finished_at": _utc_now(),
            "result": result,
            "error": None,
        })
    except Exception as exc:
        # O traceback completo fica no terminal/log do backend; a API expõe mensagem concisa.
        traceback.print_exc()
        status_payload.update({
            "status": "failed",
            "message": "A geração falhou. É possível tentar novamente; se houver checkpoint válido, o pipeline tentará retomar a partir dele. Consulte os logs do backend.",
            "resume_available": (job_dir / ".checkpoints" / "pipeline_state.pkl").is_file() and (job_dir / ".checkpoints" / "pipeline_state.json").is_file(),
            "finished_at": _utc_now(),
            "result": None,
            "error": str(exc),
        })
    finally:
        try:
            _write_status(job_dir, status_payload)
        except Exception:
            traceback.print_exc()
