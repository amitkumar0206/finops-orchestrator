#!/usr/bin/env bash
# Safe utilities to inspect, migrate, and clean up Athena results buckets
# - Defaults to dry-run. Requires AWS CLI configured.

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info(){ echo -e "${BLUE}[INFO]${NC} $1"; }
log_success(){ echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warning(){ echo -e "${YELLOW}[WARNING]${NC} $1"; }
log_error(){ echo -e "${RED}[ERROR]${NC} $1"; }

usage(){
  cat <<EOF
Usage: $0 [command] [--execute]

Commands:
  show           Show current workgroup output location and detected result buckets
  migrate        Copy historical results from legacy buckets/prefixes to canonical bucket
  clean          Remove empty legacy results prefixes and optionally empty buckets (safe)

Options:
  --env <file>   Path to deployment.env (default: deployment.env)
  --execute      Actually perform copy/delete operations (default: dry-run)
  --region <r>   AWS region (default from env or us-east-1)

Environment detection:
  - Canonical results bucket is read from ATHENA_RESULTS_BUCKET in deployment.env.
  - If unset, defaults to finops-intelligence-platform-athena-results-<account>.

Examples:
  $0 show
  $0 migrate --execute
  $0 clean   # dry-run
  $0 clean --execute
EOF
}

cmd=${1:-show}
shift || true

ENV_FILE="deployment.env"
EXECUTE=0
AWS_REGION="${AWS_REGION:-us-east-1}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env) ENV_FILE="$2"; shift 2;;
    --execute) EXECUTE=1; shift;;
    --region) AWS_REGION="$2"; shift 2;;
    -h|--help) usage; exit 0;;
    *) log_error "Unknown arg: $1"; usage; exit 1;;
  esac
done

# Load account id
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

# Determine canonical results bucket
RESULTS_BUCKET=""
if [[ -f "$ENV_FILE" ]]; then
  RESULTS_BUCKET=$(awk -F'=' '$1=="ATHENA_RESULTS_BUCKET"{print $2}' "$ENV_FILE")
fi
if [[ -z "$RESULTS_BUCKET" ]]; then
  RESULTS_BUCKET="finops-intelligence-platform-athena-results-${ACCOUNT_ID}"
fi

# Helper: ensure results bucket exists
ensure_results_bucket(){
  if aws s3api head-bucket --bucket "$RESULTS_BUCKET" --region "$AWS_REGION" >/dev/null 2>&1; then
    return 0
  fi
  log_warning "Results bucket $RESULTS_BUCKET does not exist. Creating..."
  aws s3 mb "s3://$RESULTS_BUCKET" --region "$AWS_REGION" >/dev/null 2>&1 || true
  aws s3api put-bucket-encryption --bucket "$RESULTS_BUCKET" \
    --server-side-encryption-configuration '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"},"BucketKeyEnabled":true}]}' \
    --region "$AWS_REGION" >/dev/null 2>&1 || true
  aws s3api put-bucket-versioning --bucket "$RESULTS_BUCKET" \
    --versioning-configuration Status=Enabled --region "$AWS_REGION" >/dev/null 2>&1 || true
}

# Detect current workgroup output
current_workgroup_output(){
  local wg="${ATHENA_WORKGROUP:-finops-workgroup}"
  aws athena get-work-group --work-group "$wg" --region "$AWS_REGION" \
    --query 'WorkGroup.Configuration.ResultConfiguration.OutputLocation' --output text 2>/dev/null || echo "UNKNOWN"
}

# Find buckets that look like results buckets
find_candidate_buckets(){
  aws s3api list-buckets --query 'Buckets[].Name' --output text | tr '\t' '\n' | \
    grep -E "finops|athena|result|analytics|query" || true
}

# Show
if [[ "$cmd" == "show" ]]; then
  log_info "Athena workgroup: ${ATHENA_WORKGROUP:-finops-workgroup}"
  log_info "Workgroup OutputLocation: $(current_workgroup_output)"
  log_info "Canonical results bucket: s3://$RESULTS_BUCKET/"
  echo ""
  log_info "Candidate buckets (name match):"
  find_candidate_buckets | sed 's/^/  - /' || true
  exit 0
fi

# Migrate
if [[ "$cmd" == "migrate" ]]; then
  ensure_results_bucket
  log_info "Scanning for legacy Athena results to migrate to s3://$RESULTS_BUCKET/ (dry-run=$((EXECUTE==0)))"

  # Heuristic: search all buckets for standard Athena result prefixes
  mapfile -t buckets < <(find_candidate_buckets)
  for b in "${buckets[@]}"; do
    [[ "$b" == "$RESULTS_BUCKET" ]] && continue
    # Common legacy prefixes
    for p in "athena-results" "athena" "query-results"; do
      if aws s3 ls "s3://$b/$p/" --region "$AWS_REGION" >/dev/null 2>&1; then
        log_info "Found results prefix: s3://$b/$p/"
        if [[ $EXECUTE -eq 1 ]]; then
          aws s3 sync "s3://$b/$p/" "s3://$RESULTS_BUCKET/migrated/$b/$p/" --only-show-errors || true
        else
          log_info "DRY-RUN: aws s3 sync s3://$b/$p/ s3://$RESULTS_BUCKET/migrated/$b/$p/"
        fi
      fi
    done
  done
  log_success "Migration scan complete"
  exit 0
fi

# Clean
if [[ "$cmd" == "clean" ]]; then
  log_info "Cleaning legacy empty results prefixes/buckets (dry-run=$((EXECUTE==0)))"
  mapfile -t buckets < <(find_candidate_buckets)
  for b in "${buckets[@]}"; do
    [[ "$b" == "$RESULTS_BUCKET" ]] && continue
    for p in "athena-results" "athena" "query-results"; do
      if aws s3 ls "s3://$b/$p/" --region "$AWS_REGION" >/dev/null 2>&1; then
        # If prefix appears empty (<= 1 listing line), propose delete
        cnt=$(aws s3 ls "s3://$b/$p/" --region "$AWS_REGION" | wc -l | tr -d ' ')
        if [[ "$cnt" -le 1 ]]; then
          log_warning "Empty-ish prefix detected: s3://$b/$p/"
          if [[ $EXECUTE -eq 1 ]]; then
            aws s3 rm "s3://$b/$p/" --recursive --only-show-errors || true
          else
            log_info "DRY-RUN: aws s3 rm s3://$b/$p/ --recursive"
          fi
        fi
      fi
    done
    # Attempt deleting bucket only if truly empty (succeeds only when empty)
    if [[ $EXECUTE -eq 1 ]]; then
      aws s3api delete-bucket --bucket "$b" --region "$AWS_REGION" >/dev/null 2>&1 || true
    else
      log_info "DRY-RUN: aws s3api delete-bucket --bucket $b --region $AWS_REGION"
    fi
  done
  log_success "Cleanup pass complete"
  exit 0
fi

usage
exit 1
