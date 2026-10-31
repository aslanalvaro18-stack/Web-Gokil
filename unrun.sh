#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
RUN_DIR="$ROOT_DIR/.run"

stop_service() {
  local name="$1"
  local pid_file="$2"
  local expected="$3"

  if [[ ! -f "$pid_file" ]]; then
    printf '%s tidak dijalankan oleh run.sh.\n' "$name"
    return
  fi

  local pid command_line
  pid="$(<"$pid_file")"
  if [[ ! "$pid" =~ ^[0-9]+$ ]] || ! kill -0 "$pid" 2>/dev/null; then
    rm -f -- "$pid_file"
    printf '%s sudah berhenti.\n' "$name"
    return
  fi

  command_line="$(ps -p "$pid" -o args= 2>/dev/null || true)"
  if [[ "$command_line" != *"$expected"* ]]; then
    printf 'Tidak menghentikan PID %s: command tidak cocok dengan %s.\n' "$pid" "$name" >&2
    return 1
  fi

  kill -TERM "$pid"
  rm -f -- "$pid_file"
  printf '%s dihentikan.\n' "$name"
}

stop_service 'Frontend' "$RUN_DIR/frontend.pid" "$ROOT_DIR/frontend/node_modules/vite/bin/vite.js"
stop_service 'Backend' "$RUN_DIR/backend.pid" "$ROOT_DIR/backend"