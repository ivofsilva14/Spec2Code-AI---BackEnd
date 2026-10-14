"""Endpoint para upload local dos quatro datasets JSON."""

from __future__ import annotations

import shutil
import uuid

from fastapi import APIRouter, File, HTTPException, UploadFile, status

from app.core import settings
from app.services.dataset_service import (
    DatasetServiceError,
    REQUIRED_DATASET_NAMES,
    validate_uploaded_datasets,
)

router = APIRouter(prefix="/api/datasets", tags=["datasets"])

# Nomes fixos: o nome enviado pelo cliente nunca é usado como caminho no disco.
DATASET_FILENAMES = {
    "requisitos_funcionais": "requisitos_funcionais.json",
    "requisitos_nao_funcionais": "requisitos_nao_funcionais.json",
    "regras_negocio": "regras_negocio.json",
    "projetos_interiores": "projetos_interiores.json",
}


@router.post(
    "/upload",
    status_code=status.HTTP_201_CREATED,
    summary="Enviar e validar os quatro datasets",
    description=(
        "Recebe os quatro arquivos JSON, valida seu conteúdo e salva cópias "
        "localmente em workspace/jobs/{job_id}/datasets. Nenhum arquivo é "
        "enviado ao Google Drive."
    ),
)
async def upload_datasets(
    requisitos_funcionais: UploadFile = File(..., description="JSON de requisitos funcionais"),
    requisitos_nao_funcionais: UploadFile = File(..., description="JSON de requisitos não funcionais"),
    regras_negocio: UploadFile = File(..., description="JSON de regras de negócio"),
    projetos_interiores: UploadFile = File(..., description="JSON de projetos de interiores"),
) -> dict:
    """Valida os arquivos e grava os quatro JSONs no workspace local."""
    uploads = {
        "requisitos_funcionais": requisitos_funcionais,
        "requisitos_nao_funcionais": requisitos_nao_funcionais,
        "regras_negocio": regras_negocio,
        "projetos_interiores": projetos_interiores,
    }

    try:
        # Valida todos os arquivos antes de persistir qualquer um deles.
        await validate_uploaded_datasets(uploads)
    except DatasetServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    job_id = uuid.uuid4().hex
    jobs_root = (settings.workspace_dir / "jobs").resolve()
    job_dir = (jobs_root / job_id).resolve()
    datasets_dir = job_dir / "datasets"

    # Defesa adicional para garantir que o destino esteja dentro do workspace.
    if jobs_root not in job_dir.parents:
        raise HTTPException(status_code=500, detail="Diretório de execução inválido.")

    try:
        datasets_dir.mkdir(parents=True, exist_ok=False)
        saved_files: dict[str, dict[str, str | int]] = {}
        total_bytes = 0

        for logical_name in REQUIRED_DATASET_NAMES:
            upload = uploads[logical_name]
            await upload.seek(0)
            content = await upload.read(settings.max_upload_size_bytes + 1)

            if len(content) > settings.max_upload_size_bytes:
                raise DatasetServiceError(
                    f"O arquivo '{DATASET_FILENAMES[logical_name]}' excede "
                    f"o limite de {settings.max_upload_size_mb} MB."
                )

            total_bytes += len(content)
            if total_bytes > settings.max_upload_size_bytes:
                raise DatasetServiceError(
                    f"O tamanho combinado dos arquivos excede "
                    f"o limite de {settings.max_upload_size_mb} MB."
                )

            target = datasets_dir / DATASET_FILENAMES[logical_name]
            target.write_bytes(content)
            saved_files[logical_name] = {
                "filename": target.name,
                "size_bytes": len(content),
            }

        return {
            "job_id": job_id,
            "status": "datasets_uploaded",
            "storage": "local",
            "datasets_path": str(datasets_dir.relative_to(settings.workspace_dir.resolve())),
            "files": saved_files,
            "message": "Os quatro datasets foram validados e salvos localmente.",
        }
    except DatasetServiceError as exc:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except OSError as exc:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Não foi possível salvar os datasets no armazenamento local.",
        ) from exc
    finally:
        for upload in uploads.values():
            await upload.close()
