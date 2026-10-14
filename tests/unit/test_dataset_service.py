import pytest

from app.services.dataset_service import (
    DatasetServiceError,
    validate_dataset_payloads,
)


def valid_datasets():
    return {
        "requisitos_funcionais": {"requisitos": [{"id": "RF-001"}]},
        "requisitos_nao_funcionais": {"requisitos_nao_funcionais": [{"id": "RNF-001"}]},
        "regras_negocio": {"regras_negocio": [{"id": "RN-001"}]},
        "projetos_interiores": {
            "projetos": [{"id": "P-001", "cliente": "Cliente", "ambiente": "Cozinha"}]
        },
    }


def test_validate_dataset_payloads_preserves_notebook_keys():
    result = validate_dataset_payloads(valid_datasets())
    assert result["requisitos_funcionais"]["requisitos"][0]["id"] == "RF-001"
    assert result["projetos_interiores"]["projetos"][0]["ambiente"] == "Cozinha"


def test_rejects_missing_dataset():
    with pytest.raises(DatasetServiceError, match="Datasets ausentes"):
        validate_dataset_payloads({})


def test_rejects_project_missing_required_fields():
    payload = valid_datasets()
    payload["projetos_interiores"] = {"projetos": [{"id": "P-001"}]}
    with pytest.raises(DatasetServiceError, match="cliente"):
        validate_dataset_payloads(payload)
