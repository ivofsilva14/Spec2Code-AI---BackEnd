from __future__ import annotations
import json
import os
import shutil
import subprocess
import hashlib
from pathlib import Path
from typing import Any
from google import genai
from .notebook_cells import NOTEBOOK_CELLS
import os
import time
from pathlib import Path

MODEL_NAME_DEFAULT = "gemini-3.5-flash-lite"


def carregar_dataset(datasets: dict[str, Any]) -> dict[str, Any]:
    """Valida e normaliza os quatro datasets esperados pelo notebook."""
    aliases = {
        "requisitos_funcionais": ("requisitos_funcionais", "rf"),
        "requisitos_nao_funcionais": ("requisitos_nao_funcionais", "rnf"),
        "regras_negocio": ("regras_negocio", "rn"),
        "projetos_interiores": ("projetos_interiores", "projetos"),
    }
    result = {}
    for canonical, names in aliases.items():
        found = next((datasets[n] for n in names if n in datasets), None)
        if found is None:
            raise ValueError(f"Dataset obrigatório ausente: {canonical}")
        if not isinstance(found, dict):
            raise ValueError(f"O dataset {canonical} deve conter um objeto JSON.")
        result[canonical] = found
    if not isinstance(result["projetos_interiores"].get("projetos"), list) or not result["projetos_interiores"]["projetos"]:
        raise ValueError("O dataset projetos_interiores precisa conter uma lista não vazia em 'projetos'.")
    return result


def _preparar_output(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for name in ("analysis", "architecture", "plans", "code", "tests", "traceability"):
        (output_dir / name).mkdir(parents=True, exist_ok=True)


def substituir_manifesto_com_retry(
    temp_manifest: Path,
    manifest_file: Path,
    max_tentativas: int = 8,
    intervalo: float = 0.5,
) -> None:
    """
    Tenta substituir o manifesto do checkpoint novamente
    quando o Windows bloquear temporariamente o arquivo.
    """
    ultimo_erro = None

    for tentativa in range(max_tentativas):
        try:
            os.replace(str(temp_manifest), str(manifest_file))
            return
        except PermissionError as erro:
            ultimo_erro = erro

            if tentativa < max_tentativas - 1:
                time.sleep(intervalo * (tentativa + 1))

    raise PermissionError(
        f"Não foi possível atualizar o manifesto após "
        f"{max_tentativas} tentativas. "
        f"Arquivo: {manifest_file}. "
        "Verifique bloqueios do OneDrive, antivírus ou "
        "execuções concorrentes do pipeline."
    ) from ultimo_erro


def executar_pipeline(datasets: dict[str, Any], output_dir: str | Path, resume: bool = True) -> dict[str, Any]:
    """Executa o fluxo extraído do notebook e grava artefatos em output_dir.

    datasets: dict com requisitos_funcionais, requisitos_nao_funcionais,
              regras_negocio e projetos_interiores (ou aliases rf/rnf/rn/projetos).
    output_dir: pasta final que receberá analysis/, architecture/, plans/, code/ etc.
    Requer GEMINI_API_KEY, .NET SDK 8 e Node.js/npm instalados localmente.
    """
    data = carregar_dataset(datasets)
    out = Path(output_dir).expanduser().resolve()
    if out.name != "output":
        raise ValueError("Para preservar os caminhos do notebook, output_dir deve terminar com o nome 'output'. Ex.: ./workspace/output")
    checkpoint_dir = out.parent / ".checkpoints"
    # Checkpoint persistido como manifesto JSON. Não serializamos o namespace do
    # notebook: funções criadas por exec compartilham globals e acabam incluindo
    # clientes/sessões/locks impossíveis de serializar.
    manifest_file = checkpoint_dir / "pipeline_state.json"
    checkpoint_state = None
    can_resume = False
    if resume and manifest_file.is_file():
        try:
            checkpoint_state = json.loads(manifest_file.read_text(encoding="utf-8"))
            can_resume = (
                checkpoint_state.get("status") == "in_progress"
                and isinstance(checkpoint_state.get("next_cell_position"), int)
                and checkpoint_state.get("next_cell_position", 0) > 0
            )
        except (OSError, json.JSONDecodeError):
            checkpoint_state = None
            can_resume = False
    if out.exists() and any(out.iterdir()) and not can_resume:
        raise FileExistsError(
            f"A pasta de saída não está vazia e não há checkpoint recuperável: {out}. "
            "Use um job novo ou mantenha os arquivos .checkpoints da execução anterior."
        )
    base_dir = out.parent
    _preparar_output(out)
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("Defina a variável de ambiente GEMINI_API_KEY antes de executar.")
    client = genai.Client(api_key=api_key, http_options={"api_version": "v1"})
    # Compatibilidade com anotações do notebook executadas via exec().
    # Pydantic precisa resolver nomes como List/Optional no namespace do modelo.
    from typing import List, Optional, Dict, Any, Union, Literal

    namespace = {
        "List": List, "Optional": Optional, "Dict": Dict, "Any": Any,
        "Union": Union, "Literal": Literal,
        "__name__": "app_engine_legacy_runtime",
        "os": os, "json": json, "shutil": shutil, "subprocess": subprocess,
        "BASE_DIR": str(base_dir),
         "MODEL_NAME": os.getenv("GEMINI_MODEL_NAME", MODEL_NAME_DEFAULT),
        "MODEL_ANALISTA": os.getenv("GEMINI_MODEL_ANALISTA", os.getenv("GEMINI_MODEL_NAME", MODEL_NAME_DEFAULT)),
        "MODEL_DESENVOLVEDOR": os.getenv("GEMINI_MODEL_DESENVOLVEDOR", "gemini-3.5-flash"),
        "client": client, "GEMINI_API_KEY": api_key,
        "rf": data["requisitos_funcionais"],
        "rnf": data["requisitos_nao_funcionais"],
        "rn": data["regras_negocio"],
        "projetos": data["projetos_interiores"],
    }
    namespace["projeto"] = data["projetos_interiores"]["projetos"][0]
    namespace["PROJETO_ID"] = str(namespace["projeto"].get("id", "")).strip()
    if not namespace["PROJETO_ID"]:
        raise ValueError("O primeiro projeto do dataset precisa ter um campo 'id'.")

    # Identifica se o checkpoint pertence aos mesmos datasets e à mesma versão
    # das células. Se não corresponder, inicia uma execução limpa.
    dataset_fingerprint = hashlib.sha256(
        json.dumps(data, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    cells_fingerprint = hashlib.sha256(
        json.dumps([(c["index"], c["source"]) for c in NOTEBOOK_CELLS], ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    start_at = 0
    completed = []
    replay_until = 0
    if can_resume and checkpoint_state:
        if (
            checkpoint_state.get("dataset_fingerprint") == dataset_fingerprint
            and checkpoint_state.get("cells_fingerprint") == cells_fingerprint
        ):
            # Reconstrói o namespace executando as células anteriores em ordem.
            # O estado em memória não é serializado; as células do projeto devem
            # reaproveitar artefatos já salvos sempre que houver cache em disco.
            replay_until = min(
                int(checkpoint_state.get("next_cell_position", 0)),
                len(NOTEBOOK_CELLS),
            )
            # Reconta as células durante a reconstrução; evita duplicar índices
            # no manifesto ao reexecutar as células anteriores.
            completed = []
            import logging
            logging.getLogger(__name__).info(
                "Checkpoint encontrado após célula %s; reconstruindo o contexto "
                "executando as %s células anteriores antes de continuar.",
                checkpoint_state.get("last_completed_cell"),
                replay_until,
            )
        else:
            import logging
            logging.getLogger(__name__).warning(
                "Checkpoint ignorado: datasets ou versão das células foram alterados."
            )
            can_resume = False
            replay_until = 0
            completed = []
    elif can_resume:
        can_resume = False

    for position, cell in enumerate(NOTEBOOK_CELLS):
        idx = cell["index"]
        source = cell["source"]
        if idx == 78:
            source = source.replace('PROJ-001_analise.json', '{PROJETO_ID}_analise.json')
            source = source.replace('PROJ-001_arquitetura.json', '{PROJETO_ID}_arquitetura.json')
        try:
            exec(compile(source, f"notebook_cell_{idx}", "exec"), namespace, namespace)
            from pydantic import BaseModel
            for model_name, model_class in list(namespace.items()):
                if isinstance(model_class, type) and issubclass(model_class, BaseModel) and model_class is not BaseModel:
                    model_class.model_rebuild(force=True, _types_namespace=namespace)
            # Manifesto é salvo atomicamente e não depende de serializar objetos
            # Python (clientes Gemini, locks, classes, funções ou sessões HTTP).
            completed.append(idx)
            try:
                temp_manifest = manifest_file.with_suffix(".json.tmp")
                temp_manifest.write_text(json.dumps({
                    "status": "in_progress",
                    "dataset_fingerprint": dataset_fingerprint,
                    "cells_fingerprint": cells_fingerprint,
                    "next_cell_position": position + 1,
                    "completed_cells": completed,
                    "last_completed_cell": idx,
                    "replay_strategy": "rebuild_namespace_from_cells_and_artifacts",
                }, ensure_ascii=False, indent=2), encoding="utf-8")
                #temp_manifest.replace(manifest_file)
                substituir_manifesto_com_retry(
                    temp_manifest,
                    manifest_file,
                )
            except Exception as checkpoint_exc:
                import logging
                logging.getLogger(__name__).exception(
                    "Falha ao salvar manifesto de checkpoint após célula %s: %s",
                    idx, checkpoint_exc
                )
        except Exception as exc:
            raise RuntimeError(f"Falha na célula migrada {idx}: {exc}") from exc

    # Marca a execução concluída; não oferecer uma retomada antiga após sucesso.
    try:
        final_state = {
            "status": "completed",
            "dataset_fingerprint": dataset_fingerprint,
            "cells_fingerprint": cells_fingerprint,
            "next_cell_position": len(NOTEBOOK_CELLS),
            "completed_cells": completed,
            "last_completed_cell": completed[-1] if completed else None,
            "replay_strategy": "rebuild_namespace_from_cells_and_artifacts",
        }
        temp_manifest = manifest_file.with_suffix(".json.tmp")
        temp_manifest.write_text(json.dumps(final_state, ensure_ascii=False, indent=2), encoding="utf-8")
        #temp_manifest.replace(manifest_file)
        substituir_manifesto_com_retry(
            temp_manifest,
            manifest_file,
        )
    except Exception:
        import logging
        logging.getLogger(__name__).exception("Não foi possível marcar o checkpoint como concluído.")
    return {
        "projeto_id": namespace["PROJETO_ID"],
        "output_dir": str(out),
        "cells_executed": completed,
        "resumed_from_checkpoint": can_resume and replay_until > 0,
        "last_checkpoint_cell": completed[-1] if completed else None,
    }

