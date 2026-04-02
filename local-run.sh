#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_DIR="$REPO_ROOT/.local-run"
LOG_DIR="$STATE_DIR/logs"
BACKEND_PID_FILE="$STATE_DIR/backend.pid"
FRONTEND_PID_FILE="$STATE_DIR/frontend.pid"
BACKEND_LOG="$LOG_DIR/backend.log"
FRONTEND_LOG="$LOG_DIR/frontend.log"

BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"
BACKEND_RELOAD="${BACKEND_RELOAD:-false}"
BACKEND_HEALTH_TIMEOUT="${BACKEND_HEALTH_TIMEOUT:-180}"
AUTO_INSTALL_DEPS="${AUTO_INSTALL_DEPS:-true}"

mkdir -p "$LOG_DIR"

print_help() {
  cat <<EOF
Usage: ./local-run.sh <start|stop|restart|status|logs>

Commands:
  start    Start postgres+valkey (Docker), backend, and frontend
  stop     Stop backend, frontend, and postgres+valkey
  restart  Stop then start everything
  status   Show service status
  logs     Tail backend/frontend logs

Environment overrides:
  BACKEND_PORT (default: 8000)
  FRONTEND_PORT (default: 3000)

Notes:
  - Backend runs on host, so it uses your local AWS credential chain (~/.aws, AWS_PROFILE, SSO, etc.)
  - Optional env files auto-loaded if present: deployment.env, backend/.env
  - Fresh checkout bootstrap is automatic by default; set AUTO_INSTALL_DEPS=false to disable
EOF
}

find_python_cmd() {
  if command -v python3 >/dev/null 2>&1; then
    echo "python3"
    return 0
  fi

  if command -v python >/dev/null 2>&1; then
    echo "python"
    return 0
  fi

  return 1
}

is_pid_running() {
  local pid_file="$1"
  if [[ ! -f "$pid_file" ]]; then
    return 1
  fi

  local pid
  pid="$(cat "$pid_file" 2>/dev/null || true)"
  if [[ -z "$pid" ]]; then
    return 1
  fi

  if kill -0 "$pid" 2>/dev/null; then
    return 0
  fi

  return 1
}

stop_pid() {
  local name="$1"
  local pid_file="$2"

  if is_pid_running "$pid_file"; then
    local pid
    pid="$(cat "$pid_file")"
    echo "Stopping $name (pid: $pid)..."
    kill "$pid" 2>/dev/null || true

    for _ in {1..20}; do
      if ! kill -0 "$pid" 2>/dev/null; then
        break
      fi
      sleep 0.25
    done

    if kill -0 "$pid" 2>/dev/null; then
      echo "Force killing $name (pid: $pid)..."
      kill -9 "$pid" 2>/dev/null || true
    fi
  else
    echo "$name is not running."
  fi

  rm -f "$pid_file"
}

stop_port_listener() {
  local name="$1"
  local port="$2"

  local port_pids
  port_pids="$(lsof -ti tcp:"$port" 2>/dev/null || true)"
  if [[ -z "$port_pids" ]]; then
    return
  fi

  echo "Stopping $name listener(s) on port $port..."
  while IFS= read -r pid; do
    if [[ -n "$pid" ]]; then
      kill "$pid" 2>/dev/null || true
    fi
  done <<< "$port_pids"

  sleep 1

  # If still listening, force kill remaining process(es).
  port_pids="$(lsof -ti tcp:"$port" 2>/dev/null || true)"
  if [[ -n "$port_pids" ]]; then
    echo "Force killing $name listener(s) on port $port..."
    while IFS= read -r pid; do
      if [[ -n "$pid" ]]; then
        kill -9 "$pid" 2>/dev/null || true
      fi
    done <<< "$port_pids"
  fi
}

load_env_files() {
  if [[ -f "$REPO_ROOT/deployment.env" ]]; then
    set +u
    set -a
    # shellcheck disable=SC1091
    source "$REPO_ROOT/deployment.env"
    set +a
    set -u
  fi

  if [[ -f "$REPO_ROOT/backend/.env" ]]; then
    set +u
    set -a
    # shellcheck disable=SC1091
    source "$REPO_ROOT/backend/.env"
    set +a
    set -u
  fi
}

resolve_aws_account_id() {
  if [[ -n "${AWS_ACCOUNT_ID:-}" ]]; then
    return
  fi

  if ! command -v aws >/dev/null 2>&1; then
    export AWS_ACCOUNT_ID="local"
    return
  fi

  local account_id
  account_id="$(aws sts get-caller-identity --query Account --output text 2>/dev/null || true)"
  if [[ -n "$account_id" && "$account_id" != "None" ]]; then
    export AWS_ACCOUNT_ID="$account_id"
  else
    export AWS_ACCOUNT_ID="local"
  fi
}

ensure_prereqs() {
  if ! command -v docker >/dev/null 2>&1; then
    echo "ERROR: docker is required."
    exit 1
  fi

  if ! command -v npm >/dev/null 2>&1; then
    echo "ERROR: npm is required."
    exit 1
  fi

  if ! find_python_cmd >/dev/null 2>&1; then
    echo "ERROR: python3 (or python) is required."
    exit 1
  fi

  bootstrap_backend
  bootstrap_frontend
}

bootstrap_backend() {
  local python_cmd
  python_cmd="$(find_python_cmd)"

  if [[ ! -x "$REPO_ROOT/.venv/bin/python" ]]; then
    if [[ "$AUTO_INSTALL_DEPS" != "true" ]]; then
      echo "ERROR: Python venv not found at $REPO_ROOT/.venv/bin/python"
      echo "Set AUTO_INSTALL_DEPS=true or create it manually."
      exit 1
    fi

    echo "Bootstrapping backend virtualenv..."
    (
      cd "$REPO_ROOT"
      "$python_cmd" -m venv .venv
    )
  fi

  if ! "$REPO_ROOT/.venv/bin/python" -c "import uvicorn" >/dev/null 2>&1; then
    if [[ "$AUTO_INSTALL_DEPS" != "true" ]]; then
      echo "ERROR: backend Python dependencies are missing in .venv"
      echo "Set AUTO_INSTALL_DEPS=true or install them manually with pip install -r backend/requirements.txt"
      exit 1
    fi

    echo "Installing backend Python dependencies..."
    (
      cd "$REPO_ROOT"
      "$REPO_ROOT/.venv/bin/python" -m pip install --upgrade pip
      "$REPO_ROOT/.venv/bin/python" -m pip install -r backend/requirements.txt
    )
  fi
}

bootstrap_frontend() {
  if [[ -d "$REPO_ROOT/frontend/node_modules" ]]; then
    return
  fi

  if [[ "$AUTO_INSTALL_DEPS" != "true" ]]; then
    echo "ERROR: frontend/node_modules missing. Run: cd frontend && npm install"
    exit 1
  fi

  echo "Installing frontend dependencies..."
  (
    cd "$REPO_ROOT/frontend"
    if [[ -f package-lock.json ]]; then
      npm ci
    else
      npm install
    fi
  )
}

start_docker_deps() {
  echo "Starting Docker dependencies (postgres, valkey)..."
  (
    cd "$REPO_ROOT"
    resolve_aws_account_id
    docker compose up -d postgres valkey
  )
}

start_backend() {
  if is_pid_running "$BACKEND_PID_FILE"; then
    echo "Backend already running (pid: $(cat "$BACKEND_PID_FILE"))."
    return
  fi

  load_env_files

  export ENVIRONMENT="${ENVIRONMENT:-development}"
  export TRUSTED_PROXY_COUNT="${TRUSTED_PROXY_COUNT:-0}"
  export SECRET_KEY="${SECRET_KEY:-local-dev-secret-key-change-me-1234567890}"

  # Default to config-backed demo auth for local login screen compatibility.
  export DEMO_MODE="${DEMO_MODE:-true}"
  export DEMO_IDENTITY_ENABLED="${DEMO_IDENTITY_ENABLED:-true}"
  export DATABASE_ENABLED="${DATABASE_ENABLED:-false}"
  export CHAT_HISTORY_ENABLED="${CHAT_HISTORY_ENABLED:-false}"
  export POSTGRES_HOST="${POSTGRES_HOST:-localhost}"
  export POSTGRES_PORT="${POSTGRES_PORT:-5432}"
  export POSTGRES_DB="${POSTGRES_DB:-aasmaa}"
  export POSTGRES_USER="${POSTGRES_USER:-aasmaa}"
  export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-aasmaa_password}"

  export VALKEY_HOST="${VALKEY_HOST:-localhost}"
  export VALKEY_PORT="${VALKEY_PORT:-6379}"
  export VALKEY_PASSWORD="${VALKEY_PASSWORD:-valkey_password}"

  export AWS_REGION="${AWS_REGION:-us-east-1}"

  echo "Starting backend on http://localhost:$BACKEND_PORT ..."

  # Clear stale listeners from previous crashed runs.
  local port_pids
  port_pids="$(lsof -ti tcp:"$BACKEND_PORT" 2>/dev/null || true)"
  if [[ -n "$port_pids" ]]; then
    echo "Port $BACKEND_PORT already in use. Stopping stale process(es)..."
    while IFS= read -r pid; do
      if [[ -n "$pid" ]]; then
        kill "$pid" 2>/dev/null || true
      fi
    done <<< "$port_pids"
    sleep 1
  fi

  (
    cd "$REPO_ROOT"
    if [[ "$BACKEND_RELOAD" == "true" ]]; then
      nohup "$REPO_ROOT/.venv/bin/python" -m uvicorn backend.main:app \
        --host 0.0.0.0 \
        --port "$BACKEND_PORT" \
        --reload \
        > "$BACKEND_LOG" 2>&1 &
    else
      nohup "$REPO_ROOT/.venv/bin/python" -m uvicorn backend.main:app \
        --host 0.0.0.0 \
        --port "$BACKEND_PORT" \
        > "$BACKEND_LOG" 2>&1 &
    fi
    echo $! > "$BACKEND_PID_FILE"
  )

  # Wait for backend health to become available (first run can take longer due model download).
  local waited=0
  while [[ "$waited" -lt "$BACKEND_HEALTH_TIMEOUT" ]]; do
    if curl -fsS "http://localhost:$BACKEND_PORT/health" >/dev/null 2>&1; then
      return
    fi
    sleep 1
    waited=$((waited + 1))
  done

  echo "ERROR: backend failed to become healthy on port $BACKEND_PORT after ${BACKEND_HEALTH_TIMEOUT}s."
  echo "Recent backend log lines:"
  tail -n 60 "$BACKEND_LOG" || true
  exit 1
}

start_frontend() {
  if is_pid_running "$FRONTEND_PID_FILE"; then
    echo "Frontend already running (pid: $(cat "$FRONTEND_PID_FILE"))."
    return
  fi

  echo "Starting frontend on http://localhost:$FRONTEND_PORT ..."
  (
    cd "$REPO_ROOT/frontend"
    nohup npm run dev -- --host 0.0.0.0 --port "$FRONTEND_PORT" \
      > "$FRONTEND_LOG" 2>&1 &
    echo $! > "$FRONTEND_PID_FILE"
  )
}

show_status() {
  echo "Local environment status"
  echo "------------------------"

  if is_pid_running "$BACKEND_PID_FILE"; then
    echo "Backend : running (pid: $(cat "$BACKEND_PID_FILE"))"
  else
    echo "Backend : stopped"
  fi

  if is_pid_running "$FRONTEND_PID_FILE"; then
    echo "Frontend: running (pid: $(cat "$FRONTEND_PID_FILE"))"
  else
    echo "Frontend: stopped"
  fi

  (
    cd "$REPO_ROOT"
    resolve_aws_account_id
    docker compose ps postgres valkey
  )
}

start_all() {
  ensure_prereqs
  start_docker_deps
  start_backend
  start_frontend

  echo
  echo "Started."
  echo "Backend health: http://localhost:$BACKEND_PORT/health"
  echo "Frontend     : http://localhost:$FRONTEND_PORT"
  echo "Logs         : $BACKEND_LOG, $FRONTEND_LOG"
}

stop_all() {
  stop_pid "frontend" "$FRONTEND_PID_FILE"
  stop_pid "backend" "$BACKEND_PID_FILE"

  # Fallback cleanup for orphaned servers when pid files are missing/stale.
  stop_port_listener "frontend" "$FRONTEND_PORT"
  stop_port_listener "backend" "$BACKEND_PORT"

  echo "Stopping Docker dependencies (postgres, valkey)..."
  (
    cd "$REPO_ROOT"
    resolve_aws_account_id
    docker compose stop postgres valkey >/dev/null || true
  )

  echo "Stopped."
}

logs_all() {
  touch "$BACKEND_LOG" "$FRONTEND_LOG"
  echo "Tailing logs (Ctrl+C to exit)..."
  tail -f "$BACKEND_LOG" "$FRONTEND_LOG"
}

cmd="${1:-}" 
case "$cmd" in
  start)
    start_all
    ;;
  stop)
    stop_all
    ;;
  restart)
    stop_all
    start_all
    ;;
  status)
    show_status
    ;;
  logs)
    logs_all
    ;;
  -h|--help|help|"")
    print_help
    ;;
  *)
    echo "Unknown command: $cmd"
    print_help
    exit 1
    ;;
esac
