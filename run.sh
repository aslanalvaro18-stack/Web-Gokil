#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
RUN_DIR="$ROOT_DIR/.run"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
VENV_DIR="$BACKEND_DIR/.venv"
MODEL_PATH="${AGRO_MODEL_PATH:-$BACKEND_DIR/models/teachable_machine/keras_model.h5}"
LABELS_PATH="${AGRO_LABELS_PATH:-$BACKEND_DIR/models/teachable_machine/labels.txt}"

die() {
  printf 'Error: %s\n' "$1" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "Perintah '$1' tidak ditemukan."
}

check_port_available() {
  local port="$1"
  if command -v ss >/dev/null 2>&1 && ss -ltnH "sport = :$port" | grep -q .; then
    die "Port $port sedang dipakai. Hentikan server yang ada atau pilih port lain."
  fi
}

check_pid_file() {
  local pid_file="$1"
  local service="$2"
  if [[ ! -f "$pid_file" ]]; then
    return
  fi

  local pid
  pid="$(<"$pid_file")"
  if [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null; then
    die "$service sudah berjalan dengan PID $pid. Gunakan ./unrun.sh terlebih dahulu."
  fi
  rm -f -- "$pid_file"
}

require_command python3
require_command node
require_command npm
require_command hostname

[[ -d "$BACKEND_DIR" && -d "$FRONTEND_DIR" ]] || die 'Jalankan script dari folder proyek AGRO-SEMBADA.'
check_pid_file "$RUN_DIR/backend.pid" 'Backend'
check_pid_file "$RUN_DIR/frontend.pid" 'Frontend'
check_port_available 3000
check_port_available 5173

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  python3 -m venv "$VENV_DIR"
fi
if ! "$VENV_DIR/bin/python" -c 'import fastapi, uvicorn, cv2' >/dev/null 2>&1; then
  "$VENV_DIR/bin/python" -m pip install -r "$BACKEND_DIR/requirements.txt"
fi

if [[ -z "${AGRO_MODEL_PATH:-}" && ! -f "$MODEL_PATH" && -f "$ROOT_DIR/keras_model.h5" ]]; then
  MODEL_PATH="$ROOT_DIR/keras_model.h5"
fi
if [[ -z "${AGRO_LABELS_PATH:-}" && ! -f "$LABELS_PATH" && -f "$ROOT_DIR/labels.txt" ]]; then
  LABELS_PATH="$ROOT_DIR/labels.txt"
fi
if [[ -f "$MODEL_PATH" && -f "$LABELS_PATH" ]] && \
  ! "$VENV_DIR/bin/python" -c 'import tensorflow, tf_keras' >/dev/null 2>&1; then
  "$VENV_DIR/bin/python" -m pip install -r "$BACKEND_DIR/requirements-ml.txt"
fi

if [[ ! -x "$FRONTEND_DIR/node_modules/.bin/vite" ]]; then
  npm --prefix "$FRONTEND_DIR" install
fi

mkdir -p -- "$RUN_DIR"

AGRO_MODEL_PATH="$MODEL_PATH" AGRO_LABELS_PATH="$LABELS_PATH" \
  AGRO_CAMERA_AUTOSTART="${AGRO_CAMERA_AUTOSTART:-1}" nohup "$VENV_DIR/bin/python" -m uvicorn app.main:app \
  --app-dir "$BACKEND_DIR" --host 0.0.0.0 --port 3000 --no-access-log \
  >"$RUN_DIR/backend.log" 2>&1 </dev/null &
printf '%s\n' "$!" >"$RUN_DIR/backend.pid"

nohup node "$FRONTEND_DIR/node_modules/vite/bin/vite.js" "$FRONTEND_DIR" \
  --host 0.0.0.0 --port 5173 \
  >"$RUN_DIR/frontend.log" 2>&1 </dev/null &
printf '%s\n' "$!" >"$RUN_DIR/frontend.pid"

LAN_IP="$(hostname -I | awk '{print $1}')"
printf 'AGRO-SEMBADA berjalan.\n'
printf 'Dashboard: http://%s:5173/\n' "${LAN_IP:-127.0.0.1}"
printf 'API docs:  http://%s:3000/docs\n' "${LAN_IP:-127.0.0.1}"
printf 'Log:       %s/\n' "$RUN_DIR"
printf 'Hentikan dengan: ./unrun.sh\n'