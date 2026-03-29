#!/usr/bin/env bash

# Shared deployment configuration loader.
# Priority:
# 1) Explicit DEPLOY_CONFIG_FILE
# 2) DEPLOY_CONFIG=prod|demo
# 3) Branch auto-detection (DemoOnly -> demo, otherwise prod)

resolve_repo_root() {
  if command -v git >/dev/null 2>&1; then
    local root
    root="$(git rev-parse --show-toplevel 2>/dev/null || true)"
    if [[ -n "$root" ]]; then
      printf '%s\n' "$root"
      return 0
    fi
  fi
  pwd
}

resolve_branch_name() {
  if command -v git >/dev/null 2>&1; then
    git rev-parse --abbrev-ref HEAD 2>/dev/null || echo ""
  else
    echo ""
  fi
}

load_deploy_config() {
  local repo_root config_selector branch profile config_file

  repo_root="$(resolve_repo_root)"
  config_selector="${DEPLOY_CONFIG:-auto}"

  if [[ -n "${DEPLOY_CONFIG_FILE:-}" ]]; then
    config_file="$DEPLOY_CONFIG_FILE"
    profile="custom"
  else
    if [[ "$config_selector" == "auto" ]]; then
      branch="$(resolve_branch_name)"
      if [[ "$branch" == "DemoOnly" ]]; then
        profile="demo"
      else
        profile="prod"
      fi
    elif [[ "$config_selector" == "demo" || "$config_selector" == "prod" ]]; then
      profile="$config_selector"
    else
      # Fallback to prod for unknown values
      profile="prod"
    fi

    config_file="$repo_root/config/deploy/${profile}.env"
  fi

  if [[ -f "$config_file" ]]; then
    # shellcheck disable=SC1090
    source "$config_file"
  fi

  DEPLOY_CONFIG_PROFILE="$profile"
  DEPLOY_CONFIG_FILE_RESOLVED="$config_file"
  export DEPLOY_CONFIG_PROFILE DEPLOY_CONFIG_FILE_RESOLVED
}
