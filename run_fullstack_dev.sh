#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$ROOT_DIR"
FRONTEND_DIR="$ROOT_DIR/frontend"
VENV_DIR="$BACKEND_DIR/.venv"
export UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/uv-cache}"
export NPM_CONFIG_CACHE="${NPM_CONFIG_CACHE:-/tmp/npm-cache}"

BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_HOST="${FRONTEND_HOST:-127.0.0.1}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
PYTHON_VERSION="${PYTHON_VERSION:-$(cat "$BACKEND_DIR/.python-version" 2>/dev/null || echo 3.12)}"

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "[error] '$1' bulunamadi. Lutfen yukleyip tekrar dene." >&2
    exit 1
  fi
}

setup_brew_in_path() {
  if command -v brew >/dev/null 2>&1; then
    return
  fi

  if [ -x "/opt/homebrew/bin/brew" ]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
    return
  fi

  if [ -x "/usr/local/bin/brew" ]; then
    eval "$(/usr/local/bin/brew shellenv)"
    return
  fi
}

ensure_xcode_clt() {
  if xcode-select -p >/dev/null 2>&1; then
    echo "[bootstrap] Xcode CLT zaten kurulu, skip."
    return
  fi

  echo "[bootstrap] Xcode Command Line Tools eksik. Kurulum baslatiliyor..."
  xcode-select --install >/dev/null 2>&1 || true
  echo "[error] Xcode CLT kurulumu baslatildi. Kurulum bitince script'i tekrar calistir." >&2
  exit 1
}

ensure_homebrew() {
  setup_brew_in_path
  if command -v brew >/dev/null 2>&1; then
    echo "[bootstrap] Homebrew zaten kurulu, skip."
    return
  fi

  require_cmd curl
  echo "[bootstrap] Homebrew kuruluyor..."
  NONINTERACTIVE=1 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  setup_brew_in_path

  if ! command -v brew >/dev/null 2>&1; then
    echo "[error] Homebrew kurulumu basarisiz oldu." >&2
    exit 1
  fi
}

ensure_brew_package() {
  local pkg="$1"
  local binary="$2"

  if command -v "$binary" >/dev/null 2>&1; then
    echo "[bootstrap] ${pkg} zaten kurulu, skip."
    return
  fi

  echo "[bootstrap] ${pkg} kuruluyor..."
  brew install "$pkg"

  if ! command -v "$binary" >/dev/null 2>&1; then
    echo "[error] ${pkg} kurulumu tamamlanamadi." >&2
    exit 1
  fi
}

ensure_macos_bootstrap() {
  if [ "$(uname -s)" != "Darwin" ]; then
    return
  fi

  ensure_xcode_clt
  ensure_homebrew
  ensure_brew_package uv uv
  ensure_brew_package node npm
}

check_port_free() {
  local port="$1"
  local name="$2"

  if command -v lsof >/dev/null 2>&1 && lsof -ti "tcp:${port}" >/dev/null 2>&1; then
    echo "[error] ${name} portu dolu: ${port}. BACKEND_PORT/FRONTEND_PORT ile farkli port ver." >&2
    exit 1
  fi
}

cleanup() {
  local code=$?

  if [ -n "${FRONTEND_PID:-}" ] && kill -0 "${FRONTEND_PID}" >/dev/null 2>&1; then
    kill "${FRONTEND_PID}" >/dev/null 2>&1 || true
  fi

  if [ -n "${BACKEND_PID:-}" ] && kill -0 "${BACKEND_PID}" >/dev/null 2>&1; then
    kill "${BACKEND_PID}" >/dev/null 2>&1 || true
  fi

  wait "${FRONTEND_PID:-}" >/dev/null 2>&1 || true
  wait "${BACKEND_PID:-}" >/dev/null 2>&1 || true
  exit "$code"
}

ensure_macos_bootstrap
require_cmd uv
require_cmd npm

trap cleanup EXIT INT TERM

check_port_free "$BACKEND_PORT" "backend"
check_port_free "$FRONTEND_PORT" "frontend"

echo "[setup] backend virtual env hazirlaniyor..."
cd "$BACKEND_DIR"
mkdir -p "$UV_CACHE_DIR"
mkdir -p "$NPM_CONFIG_CACHE"
echo "[setup] Python ${PYTHON_VERSION} (uv) hazirlaniyor..."
uv python install "$PYTHON_VERSION"
uv venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"
uv sync

echo "[setup] frontend bagimliliklari kuruluyor..."
cd "$FRONTEND_DIR"
if [ -f "package-lock.json" ]; then
  npm ci
else
  npm install
fi

echo "[build] frontend build aliniyor..."
npm run build

echo "[dev] backend baslatiliyor: http://${BACKEND_HOST}:${BACKEND_PORT}"
cd "$BACKEND_DIR"
uv run uvicorn main:app --host "$BACKEND_HOST" --port "$BACKEND_PORT" --reload &
BACKEND_PID=$!

echo "[dev] frontend baslatiliyor: http://${FRONTEND_HOST}:${FRONTEND_PORT}"
cd "$FRONTEND_DIR"
npm run dev -- --host "$FRONTEND_HOST" --port "$FRONTEND_PORT" &
FRONTEND_PID=$!

echo "[ok] Fullstack dev ortami calisiyor. Cikmak icin Ctrl+C."
wait -n "$BACKEND_PID" "$FRONTEND_PID"
