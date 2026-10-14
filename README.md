# TCC IA — Backend

Backend em FastAPI para validar datasets, gerenciar jobs locais e orquestrar a geração de software via pipeline multiagente com Gemini.

## Visão geral

Este projeto expõe uma API local para:

- receber e validar quatro datasets JSON obrigatórios;
- salvar os arquivos em `workspace/jobs/<job_id>/datasets/`;
- iniciar uma geração multiagente em background;
- acompanhar o status da execução;
- baixar os artefatos gerados em um arquivo ZIP;
- manter tudo no ambiente local da máquina, sem depender de Google Drive ou armazenamento externo.

O fluxo principal é baseado em um pipeline extraído do notebook do TCC, com execução de agentes que produzem análise, arquitetura, planos, código, testes e rastreabilidade.

## Estrutura do projeto

```text
Backend/
├── app/
│   ├── api/
│   │   └── routes/
│   │       ├── datasets.py
│   │       └── generation.py
│   ├── core/
│   │   └── config.py
│   ├── engine/
│   │   ├── notebook_cells.py
│   │   └── pipeline.py
│   ├── schemas/
│   │   └── dataset.py
│   ├── services/
│   │   ├── dataset_service.py
│   │   └── generation_service.py
│   ├── main.py
│   └── __init__.py
├── workspace/
├── .env
├── .env.example
├── .gitignore
├── README.md
├── requirements.txt
└── tests/
```

## Requisitos

- Python 3.11+
- pip
- .NET SDK 8 (necessário para execução real do pipeline)
- Node.js + npm (necessário para alguns passos do pipeline)
- chave de API do Google Gemini

## Instalação

No PowerShell, a partir da raiz do backend:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
```

Preencha as variáveis do arquivo `.env`, principalmente:

- `GEMINI_API_KEY`
- `GEMINI_MODEL_NAME` (fallback geral)
- `GEMINI_MODEL_ANALISTA`
- `GEMINI_MODEL_DESENVOLVEDOR`

Nunca versionar o arquivo `.env` com credenciais reais.

## Configuração de ambiente

| Variável | Descrição | Valor padrão |
|---|---|---|
| `APP_NAME` | Nome exibido pela API | `TCC IA - Gerador de Sistemas Multiagente` |
| `APP_VERSION` | Versão da aplicação | `0.1.0` |
| `APP_ENV` | Ambiente de execução | `development` |
| `GEMINI_API_KEY` | Chave da API Gemini | não definida |
| `GEMINI_MODEL_NAME` | Modelo padrão para fallback | `gemini-3.5-flash-lite` |
| `GEMINI_MODEL_ANALISTA` | Modelo usado por analista/arquiteto/testador/auditor | `gemini-3.5-flash-lite` |
| `GEMINI_MODEL_DESENVOLVEDOR` | Modelo usado por planejadores/desenvolvedores | `gemini-3.5-flash` |
| `WORKSPACE_DIR` | Diretório local de jobs e artefatos | `workspace` |
| `CORS_ORIGINS` | Origens permitidas por CORS | `http://localhost:5173,http://127.0.0.1:5173` |
| `MAX_UPLOAD_SIZE_MB` | Limite por upload | `25` |
| `JOB_TIMEOUT_SECONDS` | Tempo máximo de job planejado | `1800` |
| `GEMINI_TIMEOUT_MS` | Timeout por chamada ao Gemini | `180000` |

Caminhos relativos em `WORKSPACE_DIR` são resolvidos a partir da raiz do backend.

## Executar a API

```powershell
python -m uvicorn app.main:app --reload
```

Depois, acesse:

- Swagger UI: http://127.0.0.1:8000/docs
- Health check: http://127.0.0.1:8000/api/health
- Raiz da API: http://127.0.0.1:8000/

## Fluxo principal da API

### 1) Upload dos datasets

Endpoint:

```http
POST /api/datasets/upload
```

Campos obrigatórios:

- `requisitos_funcionais` (JSON)
- `requisitos_nao_funcionais` (JSON)
- `regras_negocio` (JSON)
- `projetos_interiores` (JSON)

A API valida a estrutura antes de salvar os arquivos e gera um `job_id` único.

Os arquivos ficam em:

```text
workspace/jobs/<job_id>/datasets/
```

Os nomes do disco são fixos e não dependem do nome original enviado pelo cliente.

### 2) Iniciar a geração

Endpoint:

```http
POST /api/generation/{job_id}/start
```

A API re-carrega os datasets do diretório local e inicia o pipeline em background.

### 3) Consultar status do job

Endpoint:

```http
GET /api/generation/{job_id}
```

Status possíveis:

- `datasets_uploaded`
- `running`
- `completed`
- `failed`

### 4) Baixar artefatos

Endpoint:

```http
GET /api/generation/{job_id}/download
```

Quando a geração termina com sucesso, os artefatos ficam em:

```text
workspace/jobs/<job_id>/output/
```

e a API disponibiliza um zip contendo esses arquivos.

## Validação dos datasets

A validação é feita em `app/services/dataset_service.py` e verifica os quatro JSONs esperados:

- `requisitos_funcionais`: deve conter uma lista `requisitos`
- `requisitos_nao_funcionais`: deve conter uma lista `requisitos_nao_funcionais`
- `regras_negocio`: deve conter uma lista `regras_negocio`
- `projetos_interiores`: deve conter uma lista `projetos` e cada projeto precisa ter pelo menos `id`, `cliente` e `ambiente`

A validação é intencionalmente flexível para não impor campos extras que o notebook ainda não exige.

## Pipeline multiagente

O motor principal está em `app/engine/pipeline.py` e executa etapas baseadas no notebook do TCC, produzindo resultados em pastas como:

- `analysis/`
- `architecture/`
- `plans/`
- `code/`
- `tests/`
- `traceability/`

O pipeline usa as variáveis `GEMINI_API_KEY`, `GEMINI_MODEL_NAME`, `GEMINI_MODEL_ANALISTA` e `GEMINI_MODEL_DESENVOLVEDOR` para se conectar ao Gemini.

## Observações importantes

- Todo o armazenamento de datasets e artefatos é local.
- O projeto não usa Google Drive como armazenamento de execução.
- O job não é sobrescrito automaticamente quando há arquivos existentes e sem checkpoint recuperável.
- O pipeline oferece suporte a retomada por checkpoint quando disponível.
- Se o serviço do Gemini estiver indisponível, a execução falha e o status do job passa para `failed`.

## Dica de teste rápido

1. Inicie a API.
2. Vá em `http://127.0.0.1:8000/docs`.
3. Execute `POST /api/datasets/upload` com os quatro JSONs.
4. Copie o `job_id` retornado.
5. Chame `POST /api/generation/{job_id}/start`.
6. Consulte `GET /api/generation/{job_id}` até finalizar.

## Licença

Este projeto é destinado ao uso acadêmico e de desenvolvimento local do TCC IA. Ajustes específicos de licença devem ser definidos pelo responsável do projeto.

