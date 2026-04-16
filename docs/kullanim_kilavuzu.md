# Detaylı Kullanım Kılavuzu

Bu doküman, `pingulacore-service` projesini sıfırdan kurup geliştirme ortamında çalıştırmak için adım adım rehberdir.

## 1. Proje Bileşenleri

- Backend: FastAPI (`/v1` API)
- Frontend: Vite + React
- Paket/ortam yönetimi: `uv` (Python), `npm` (Node)
- Varsayılan backend adresi: `http://127.0.0.1:8000`
- Varsayılan frontend adresi: `http://127.0.0.1:5173`

## 2. Önerilen Yöntem (Tek Komut)

### 2.1 macOS / Linux

```bash
./run_fullstack_dev.sh
```

Scriptin yaptığı işlemler:

- macOS'ta eksikse `Xcode CLT`, `Homebrew`, `uv`, `node/npm` kurulumunu dener.
- `PYTHON_VERSION` (varsayılan `.python-version` veya `3.12`) için Python runtime hazırlar.
- `.venv` oluşturur ve `uv sync` yapar.
- Frontend bağımlılıklarını kurar, `npm run build` alır.
- Backend + frontend dev server başlatır.
- `Ctrl+C` ile süreçleri kapatır.

### 2.2 Windows (PowerShell)

```powershell
powershell -ExecutionPolicy Bypass -File .\run_fullstack_dev.ps1
```

Scriptin yaptığı işlemler:

- `winget` ile eksikse `uv` ve `node/npm` kurulumunu dener.
- `uv python install`, `uv venv`, venv activation, `uv sync` yapar.
- Frontend kurulum + build + dev süreçlerini başlatır.
- Backend + frontend süreçlerinden biri kapanırsa diğerini de sonlandırır.

## 3. Script Ayarları (Environment Variables)

Bu değişkenler script davranışını kontrol eder:

- `BACKEND_HOST` (default: `127.0.0.1`)
- `BACKEND_PORT` (default: `8000`)
- `FRONTEND_HOST` (default: `127.0.0.1`)
- `FRONTEND_PORT` (default: `5173`)
- `PYTHON_VERSION` (default: `.python-version` içeriği veya `3.12`)
- `UV_CACHE_DIR` (default: `/tmp/uv-cache` ya da Windows `%TEMP%\uv-cache`)
- `NPM_CONFIG_CACHE` (default: `/tmp/npm-cache` ya da Windows `%TEMP%\npm-cache`)

Örnek (macOS/Linux):

```bash
BACKEND_PORT=18000 FRONTEND_PORT=15173 ./run_fullstack_dev.sh
```

Örnek (Windows PowerShell):

```powershell
$env:BACKEND_PORT=18000
$env:FRONTEND_PORT=15173
powershell -ExecutionPolicy Bypass -File .\run_fullstack_dev.ps1
```

## 4. Manuel Kurulum ve Çalıştırma

### 4.1 Backend

```bash
uv python install 3.12
uv venv .venv
source .venv/bin/activate
uv sync
uv run uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Windows venv activation:

```powershell
.\.venv\Scripts\Activate.ps1
```

### 4.2 Frontend

```bash
cd frontend
npm ci
npm run build
npm run dev -- --host 127.0.0.1 --port 5173
```

## 5. Model ve Stub Modu

Backend `.env` dosyasını otomatik yükler.

Davranış:

- `GOOGLE_API_KEY` veya `GEMINI_API_KEY` varsa gerçek model kullanılabilir.
- `ANTHROPIC_API_KEY` varsa Anthropic modelleri kullanılabilir.
- Hiç API anahtarı yoksa varsayılan olarak `stub` moduna düşer.
- `AI_USE_STUB=1` ile zorla stub mod açılabilir.

Kontrol endpointi:

```bash
curl http://127.0.0.1:8000/v1/runtime-info
```

## 6. Sık Kullanılan API Endpointleri

Pipeline:

- `POST /v1/pipelines/full/run`
- `POST /v1/pipelines/sub/yaml-to-question/run`
- `POST /v1/pipelines/sub/question-to-layout/run`
- `POST /v1/pipelines/sub/layout-to-html/run`

Agent:

- `POST /v1/agents/main/generate-question/run`
- `POST /v1/agents/main/generate-layout/run`
- `POST /v1/agents/main/generate-html/run`
- `POST /v1/agents/validation/extract-rules/run`
- `POST /v1/agents/validation/evaluate-rule/run`
- `POST /v1/agents/validation/validate-question-layout/run`
- `POST /v1/agents/validation/validate-layout-html/run`
- `POST /v1/agents/helper/generate-composite-image/run`

Log ve gözlem:

- `POST /v1/stream-keys`
- `GET /v1/logs/stream/{stream_key}` (SSE)
- `GET /v1/pipelines/{pipeline_id}`
- `GET /v1/pipelines/{pipeline_id}/logs`
- `GET /v1/sub-pipelines/{sub_pipeline_id}`

Dosya ve asset:

- `GET /v1/yaml-files`
- `GET /v1/yaml-files/{filename}`
- `GET /v1/assets/{filename}`

## 7. Test ve Doğrulama

Backend testleri:

```bash
uv run pytest -q
```

Canlı E2E:

```bash
uv run python scripts/e2e_live_check.py
./scripts/run_e2e_with_backend.sh
```

Frontend testleri:

```bash
cd frontend
npm run test
```

## 8. Sorun Giderme

`uv` izin/cached dosya hatası:

- Script zaten varsayılan olarak `UV_CACHE_DIR` ayarlar.
- Gerekirse farklı dizin ver: `UV_CACHE_DIR=/tmp/my-uv-cache`.

`npm` cache izin hatası:

- Script varsayılan `NPM_CONFIG_CACHE` kullanır.
- Gerekirse farklı dizin ver: `NPM_CONFIG_CACHE=/tmp/my-npm-cache`.

Port dolu hatası:

- `BACKEND_PORT` ve/veya `FRONTEND_PORT` değiştir.

Windows PowerShell execution policy hatası:

- Komutu `-ExecutionPolicy Bypass` ile çalıştır.

Homebrew veya winget bulunamıyor:

- macOS: önce Xcode CLT kurulumu tamamlanmalı.
- Windows: Microsoft App Installer ile `winget` aktif olmalı.

## 9. Dosya Referansları

- Otomatik script (macOS/Linux): `run_fullstack_dev.sh`
- Otomatik script (Windows): `run_fullstack_dev.ps1`
- API router'ları: `app/api/pipeline.py`, `app/api/agent.py`, `app/api/logs.py`
- Vite proxy ayarı: `frontend/vite.config.ts`
