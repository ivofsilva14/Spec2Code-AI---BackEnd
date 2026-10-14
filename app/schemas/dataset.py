"""Contratos para os quatro datasets utilizados pelo pipeline do TCC.

Os contratos validam a estrutura externa documentada no notebook. Os itens de
requisitos permanecem flexíveis para preservar os formatos detalhados do dataset.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DatasetBase(BaseModel):
    """Base que permite metadados adicionais sem ignorar campos obrigatórios."""

    model_config = ConfigDict(extra="allow")


class RequisitosFuncionaisDataset(DatasetBase):
    requisitos: list[Any] = Field(min_length=1)


class RequisitosNaoFuncionaisDataset(DatasetBase):
    requisitos_nao_funcionais: list[Any] = Field(min_length=1)


class RegrasNegocioDataset(DatasetBase):
    regras_negocio: list[Any] = Field(min_length=1)


class ProjetoInterior(DatasetBase):
    # O notebook acessa explicitamente esses três campos no fluxo de execução.
    id: str = Field(min_length=1)
    cliente: str = Field(min_length=1)
    ambiente: str = Field(min_length=1)


class ProjetosInterioresDataset(DatasetBase):
    projetos: list[ProjetoInterior] = Field(min_length=1)

    @field_validator("projetos")
    @classmethod
    def projeto_ids_devem_ser_unicos(
        cls, projetos: list[ProjetoInterior]
    ) -> list[ProjetoInterior]:
        ids = [projeto.id for projeto in projetos]
        if len(ids) != len(set(ids)):
            raise ValueError("O dataset contém IDs de projeto duplicados.")
        return projetos


class DatasetBundle(BaseModel):
    """Conjunto validado dos quatro arquivos, indexados pelos nomes lógicos."""

    model_config = ConfigDict(extra="forbid")

    requisitos_funcionais: RequisitosFuncionaisDataset
    requisitos_nao_funcionais: RequisitosNaoFuncionaisDataset
    regras_negocio: RegrasNegocioDataset
    projetos_interiores: ProjetosInterioresDataset

    def to_pipeline_dict(self) -> dict[str, dict[str, Any]]:
        """Converte para dicts Python, preservando as chaves esperadas pelo notebook."""
        return {
            nome: dataset.model_dump(mode="python")
            for nome, dataset in self.model_dump_models().items()
        }

    def model_dump_models(self) -> dict[str, DatasetBase]:
        """Retorna os quatro modelos sem serializar os itens internos."""
        return {
            "requisitos_funcionais": self.requisitos_funcionais,
            "requisitos_nao_funcionais": self.requisitos_nao_funcionais,
            "regras_negocio": self.regras_negocio,
            "projetos_interiores": self.projetos_interiores,
        }
