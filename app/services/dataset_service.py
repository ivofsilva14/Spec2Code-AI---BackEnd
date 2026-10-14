"""Leitura e validação dos datasets JSON antes da execução multiagente."""

from __future__ import annotations

import json
from typing import Any, Mapping

from fastapi import UploadFile
from pydantic import ValidationError

from app.core import settings
from app.schemas.dataset import DatasetBundle


REQUIRED_DATASET_NAMES = (
    "requisitos_funcionais",
    "requisitos_nao_funcionais",
    "regras_negocio",
    "projetos_interiores",
)


class DatasetServiceError(ValueError):
    """Erro de entrada legível para ser convertido em resposta HTTP 4xx."""


def _decode_json(content: bytes, filename: str) -> dict[str, Any]:
    if not content:
        raise DatasetServiceError(f"O arquivo '{filename}' está vazio.")

    try:
        decoded = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise DatasetServiceError(
            f"O arquivo '{filename}' deve estar codificado em UTF-8."
        ) from exc

    try:
        data = json.loads(decoded)
    except json.JSONDecodeError as exc:
        raise DatasetServiceError(
            f"JSON inválido em '{filename}' (linha {exc.lineno}, coluna {exc.colno}): {exc.msg}."
        ) from exc

    if not isinstance(data, dict):
        raise DatasetServiceError(
            f"O arquivo '{filename}' deve conter um objeto JSON na raiz, não uma lista ou valor isolado."
        )
    return data


def validate_dataset_payloads(
    datasets: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    """Valida a estrutura dos quatro datasets e retorna dicts para o pipeline.

    ``datasets`` deve usar as chaves lógicas definidas em ``REQUIRED_DATASET_NAMES``
    e os valores devem ser objetos já decodificados de JSON.
    """
    if not isinstance(datasets, Mapping):
        raise DatasetServiceError("Os datasets devem ser enviados como um objeto/mapeamento.")

    missing = [name for name in REQUIRED_DATASET_NAMES if name not in datasets]
    unexpected = [name for name in datasets if name not in REQUIRED_DATASET_NAMES]
    problems: list[str] = []
    if missing:
        problems.append("Datasets ausentes: " + ", ".join(missing) + ".")
    if unexpected:
        problems.append("Datasets não reconhecidos: " + ", ".join(map(str, unexpected)) + ".")
    if problems:
        raise DatasetServiceError(" ".join(problems))

    try:
        bundle = DatasetBundle.model_validate(dict(datasets))
    except ValidationError as exc:
        details = []
        for error in exc.errors(include_url=False):
            location = ".".join(str(part) for part in error["loc"]) or "dataset"
            details.append(f"{location}: {error['msg']}")
        raise DatasetServiceError("Estrutura dos datasets inválida: " + "; ".join(details)) from exc

    return bundle.to_pipeline_dict()


async def validate_uploaded_datasets(
    files: Mapping[str, UploadFile],
) -> dict[str, dict[str, Any]]:
    """Lê e valida os quatro arquivos enviados como multipart/form-data.

    A chave de ``files`` deve ser o nome lógico do dataset (por exemplo,
    ``requisitos_funcionais``), e cada arquivo deve conter JSON UTF-8.
    """
    missing = [name for name in REQUIRED_DATASET_NAMES if name not in files]
    unexpected = [name for name in files if name not in REQUIRED_DATASET_NAMES]
    if missing or unexpected:
        messages = []
        if missing:
            messages.append("Arquivos obrigatórios ausentes: " + ", ".join(missing) + ".")
        if unexpected:
            messages.append("Campos de arquivo não reconhecidos: " + ", ".join(map(str, unexpected)) + ".")
        raise DatasetServiceError(" ".join(messages))

    max_bytes = settings.max_upload_size_bytes
    parsed: dict[str, dict[str, Any]] = {}
    total_bytes = 0

    for name in REQUIRED_DATASET_NAMES:
        upload = files[name]
        filename = upload.filename or f"{name}.json"
        content = await upload.read(max_bytes + 1)
        if len(content) > max_bytes:
            raise DatasetServiceError(
                f"O arquivo '{filename}' excede o limite de {settings.max_upload_size_mb} MB."
            )
        total_bytes += len(content)
        if total_bytes > max_bytes:
            raise DatasetServiceError(
                f"O tamanho combinado dos arquivos excede o limite de {settings.max_upload_size_mb} MB."
            )
        parsed[name] = _decode_json(content, filename)

    return validate_dataset_payloads(parsed)
