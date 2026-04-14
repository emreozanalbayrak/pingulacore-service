# pingulacore-service

FastAPI + PydanticAI tabanlı ilkokul/ortaokul soru üretim servisi.

## Çalıştırma

```bash
uv run uvicorn main:app --reload
```

Frontend (ayrı app):

```bash
cd frontend
npm install
npm run dev
```

Frontend `http://127.0.0.1:5173` üzerinde çalışır ve `/v1` çağrılarını backend `http://127.0.0.1:8000` adresine proxy eder.

## Gerçek Agent Modu

- Backend, repo kökündeki `.env` dosyasını otomatik yükler.
- `GOOGLE_API_KEY` veya `ANTHROPIC_API_KEY` varsa varsayılan olarak `stub` kapatılır.
- İstersen zorla stub açmak için: `AI_USE_STUB=1`.
- Frontend üst kısmındaki `Agent Mode` bandı anlık modu gösterir (`Real Model` veya `Stub`).

## Modlar

- Full pipeline: `POST /v1/pipelines/full/run`
- Sub-pipeline:
  - `POST /v1/pipelines/sub/yaml-to-question/run`
  - `POST /v1/pipelines/sub/question-to-layout/run`
  - `POST /v1/pipelines/sub/layout-to-html/run`
- Standalone agent endpointleri:
  - `POST /v1/agents/main/generate-question/run`
  - `POST /v1/agents/main/generate-layout/run`
  - `POST /v1/agents/main/generate-html/run`
  - `POST /v1/agents/validation/extract-rules/run`
  - `POST /v1/agents/validation/evaluate-rule/run`
  - `POST /v1/agents/validation/validate-question-layout/run`
  - `POST /v1/agents/validation/validate-layout-html/run`
  - `POST /v1/agents/helper/generate-composite-image/run`

## Gözlem endpointleri

- `GET /v1/pipelines/{pipeline_id}`
- `GET /v1/pipelines/{pipeline_id}/agent-runs`
- `GET /v1/pipelines/{pipeline_id}/logs`
- `GET /v1/sub-pipelines/{sub_pipeline_id}`
- `GET /v1/sub-pipelines/{sub_pipeline_id}/agent-runs`
- `GET /v1/sub-pipelines/{sub_pipeline_id}/logs`
- `GET /v1/agent-runs/{agent_name}/{run_id}`

## YAML kaynak dizini

- Birincil: `ortak/`
- Fallback: `old/ortak/`

## Testler

```bash
uv run pytest -q
```

Gerçek endpoint akışıyla (pytest değil) canlı E2E script:

```bash
# backend ayrı çalışıyorsa
uv run python scripts/e2e_live_check.py

# backend'i script başlatıp test etsin:
./scripts/run_e2e_with_backend.sh
```
