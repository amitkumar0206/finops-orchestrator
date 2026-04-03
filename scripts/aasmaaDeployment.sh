#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

MODE=""
PROCESS=""
EXTRA_ARGS=()

usage() {
  cat <<'EOF'
Unified deployment command for aasmaa.

Usage:
  ./scripts/aasmaaDeployment.sh --mode=<demo|prod> --process=<deploy|update|migrate|redeploy-backend> [options]
  ./scripts/aasmaaDeployment.sh --mode demo --process update --dry-run

Examples:
  ./scripts/aasmaaDeployment.sh --mode=demo --process=update
  ./scripts/aasmaaDeployment.sh --mode=demo --process=deploy --precheck-only
  ./scripts/aasmaaDeployment.sh --mode=prod --process=update --skip-build
  ./scripts/aasmaaDeployment.sh --mode=prod --process=migrate --region ap-south-1 --stack-name aasmaa

Notes:
  - demo deploy   -> scripts/deployment/deploy-demo-barebones.sh
  - demo update   -> scripts/deployment/update-demo-barebones.sh
  - prod update   -> scripts/deployment/update-prod-full.sh
  - *  migrate    -> scripts/deployment/aws_run_migrations.sh run
EOF
}

require_script() {
  local rel_path="$1"
  local full_path="$ROOT_DIR/$rel_path"
  if [[ ! -f "$full_path" ]]; then
    echo "[aasmaaDeployment] Missing script: $rel_path" >&2
    exit 1
  fi
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode=*)
      MODE="${1#*=}"
      ;;
    --mode)
      MODE="${2:-}"
      shift
      ;;
    --process=*)
      PROCESS="${1#*=}"
      ;;
    --process)
      PROCESS="${2:-}"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      EXTRA_ARGS+=("$1")
      ;;
  esac
  shift
done

if [[ -z "$MODE" || -z "$PROCESS" ]]; then
  echo "[aasmaaDeployment] --mode and --process are required." >&2
  usage
  exit 1
fi

MODE="$(echo "$MODE" | tr '[:upper:]' '[:lower:]')"
PROCESS="$(echo "$PROCESS" | tr '[:upper:]' '[:lower:]')"

case "$MODE" in
  demo|prod)
    ;;
  *)
    echo "[aasmaaDeployment] Unsupported mode: $MODE (expected demo or prod)." >&2
    exit 1
    ;;
esac

run_script() {
  local rel_script="$1"
  shift
  require_script "$rel_script"
  echo "[aasmaaDeployment] Running: $rel_script $*"
  (cd "$ROOT_DIR" && bash "$ROOT_DIR/$rel_script" "$@")
}

if [[ "$PROCESS" == "migrate" ]]; then
  run_script "scripts/deployment/aws_run_migrations.sh" run "${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"}"
  exit 0
fi

if [[ "$MODE" == "demo" ]]; then
  case "$PROCESS" in
    deploy)
      run_script "scripts/deployment/deploy-demo-barebones.sh" "${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"}"
      ;;
    update)
      run_script "scripts/deployment/update-demo-barebones.sh" "${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"}"
      ;;
    redeploy-backend)
      run_script "scripts/deployment/redeploy-backend.sh" "${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"}"
      ;;
    *)
      echo "[aasmaaDeployment] Unsupported demo process: $PROCESS" >&2
      exit 1
      ;;
  esac
  exit 0
fi

if [[ "$MODE" == "prod" ]]; then
  case "$PROCESS" in
    update)
      run_script "scripts/deployment/update-prod-full.sh" "${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"}"
      ;;
    *)
      echo "[aasmaaDeployment] Unsupported prod process: $PROCESS" >&2
      echo "[aasmaaDeployment] Supported prod process values: update, migrate" >&2
      exit 1
      ;;
  esac
  exit 0
fi
