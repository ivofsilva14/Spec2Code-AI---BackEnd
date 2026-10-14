"""Rotas para iniciar, consultar e baixar os artefatos da geração."""

from __future__ import annotations

import os
import tempfile
import zipfile
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from fastapi.responses import FileResponse

from app.services.generation_service import (
    GenerationServiceError,
    get_job_dir,
    read_job_status,
    run_generation,
    start_generation,
)

router = APIRouter(prefix="/api/generation", tags=["generation"])


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, FileNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, GenerationServiceError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Erro interno ao processar a execução.",
    )


@router.post(
    "/{job_id}/start",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Iniciar geração multiagente",
    description=(
        "Localiza os quatro datasets em workspace/jobs/{job_id}/datasets e "
        "executa app/engine/pipeline.py em background. O armazenamento é local."
    ),
)
def start_generation_endpoint(job_id: str, background_tasks: BackgroundTasks) -> dict:
    try:
        job = start_generation(job_id)
    except (FileNotFoundError, GenerationServiceError) as exc:
        raise _http_error(exc) from exc

    background_tasks.add_task(run_generation, job_id)
    return {
        "job_id": job_id,
        "status": job["status"],
        "message": "Geração aceita e executando em segundo plano.",
        "status_url": f"/api/generation/{job_id}",
    }


@router.get(
    "/{job_id}",
    summary="Consultar status da geração",
)
def get_generation_status(job_id: str) -> dict:
    try:
        return read_job_status(job_id)
    except (FileNotFoundError, GenerationServiceError) as exc:
        raise _http_error(exc) from exc


def _create_output_zip(output_dir: Path, job_dir: Path) -> Path:
    """Cria um ZIP temporário com os arquivos de output, sem incluir o diretório raiz."""
    fd, archive_name = tempfile.mkstemp(
        prefix=".output-download-",
        suffix=".zip",
        dir=str(job_dir),
    )
    os.close(fd)
    archive_path = Path(archive_name)

    try:
        with zipfile.ZipFile(
            archive_path,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
        ) as archive:
            for path in sorted(output_dir.rglob("*")):
                # Não seguir links simbólicos: evita incluir arquivos fora do output.
                if path.is_symlink() or not path.is_file():
                    continue
                resolved = path.resolve()
                try:
                    resolved.relative_to(output_dir.resolve())
                except ValueError:
                    continue
                archive.write(path, arcname=path.relative_to(output_dir).as_posix())

        if archive_path.stat().st_size == 0:
            raise GenerationServiceError("Não foi possível criar o ZIP dos artefatos.")
        with zipfile.ZipFile(archive_path, "r") as archive:
            if not archive.namelist():
                raise GenerationServiceError("A pasta output não contém arquivos para download.")
        return archive_path
    except Exception:
        archive_path.unlink(missing_ok=True)
        raise


def _remove_archive(path: Path) -> None:
    path.unlink(missing_ok=True)


@router.get(
    "/{job_id}/download",
    response_class=FileResponse,
    summary="Baixar artefatos da geração em ZIP",
    description=(
        "Disponibiliza os arquivos de workspace/jobs/{job_id}/output em um arquivo ZIP. "
        "A geração precisa estar concluída."
    ),
    responses={
        200: {"content": {"application/zip": {}}},
        404: {"description": "Execução ou pasta output não encontrada."},
        409: {"description": "Geração ainda não concluída ou sem artefatos."},
    },
)
def download_generation_output(job_id: str, background_tasks: BackgroundTasks) -> FileResponse:
    try:
        job_dir = get_job_dir(job_id)
        job_status = read_job_status(job_id)
    except (FileNotFoundError, GenerationServiceError) as exc:
        raise _http_error(exc) from exc

    if job_status.get("status") != "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "O download só está disponível quando a geração estiver concluída. "
                f"Status atual: {job_status.get('status', 'desconhecido')}."
            ),
        )

    output_dir = job_dir / "output"
    if not output_dir.is_dir():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="A pasta de artefatos desta execução não foi encontrada.",
        )

    try:
        has_files = any(
            path.is_file() and not path.is_symlink()
            for path in output_dir.rglob("*")
        )
        if not has_files:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A geração foi marcada como concluída, mas não há arquivos para baixar.",
            )
        archive_path = _create_output_zip(output_dir, job_dir)
    except GenerationServiceError as exc:
        raise _http_error(exc) from exc
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Não foi possível compactar os artefatos desta execução.",
        ) from exc

    background_tasks.add_task(_remove_archive, archive_path)
    return FileResponse(
        path=archive_path,
        media_type="application/zip",
        filename=f"tcc_ia_{job_id}.zip",
        background=background_tasks,
    )
