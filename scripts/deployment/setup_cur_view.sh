#!/bin/bash

##############################################################################
# CUR View Setup Script
##############################################################################
# This script sets up the unified CUR view for AWS Cost and Usage Report data.
# It should be run after the Glue Crawler has discovered CUR tables.
#
# Usage:
#   ./setup_cur_view.sh [deployment.env]
##############################################################################

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOYMENT_ENV="${1:-$SCRIPT_DIR/../../deployment.env}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if deployment.env exists
if [ ! -f "$DEPLOYMENT_ENV" ]; then
    log_error "Deployment environment file not found: $DEPLOYMENT_ENV"
    exit 1
fi

# Load configuration
source "$DEPLOYMENT_ENV"

log_info "Setting up CUR unified view..."
log_info "  Database: ${AWS_CUR_DATABASE}"
log_info "  View: ${AWS_CUR_TABLE}"
log_info "  Region: ${AWS_REGION}"

# Check if Python script exists
PYTHON_SCRIPT="$SCRIPT_DIR/create_advanced_cur_view.py"
if [ ! -f "$PYTHON_SCRIPT" ]; then
    log_error "CUR view creation script not found: $PYTHON_SCRIPT"
    exit 1
fi

# Run the Python script
log_info "Running CUR view creator..."
python3 "$PYTHON_SCRIPT" "$DEPLOYMENT_ENV"

if [ $? -eq 0 ]; then
    log_success "✅ CUR view setup complete!"
    log_info ""
    log_info "Next steps:"
    log_info "  1. The backend ECS service will automatically use this view"
    log_info "  2. To refresh the view when new CUR data arrives, re-run this script"
    log_info "  3. Test queries in your application"
    exit 0
else
    log_error "CUR view setup failed"
    exit 1
fi
