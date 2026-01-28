#!/bin/bash
# Deploy Kintsugi-Helix to Google Cloud

set -euo pipefail

# Configuration
PROJECT_ID="${GOOGLE_CLOUD_PROJECT:-}"
REGION="${REGION:-us-central1}"
ENVIRONMENT="${ENVIRONMENT:-dev}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check required environment variables
check_requirements() {
    if [[ -z "$PROJECT_ID" ]]; then
        log_error "GOOGLE_CLOUD_PROJECT environment variable is required"
        exit 1
    fi

    # Check if gcloud is installed
    if ! command -v gcloud &> /dev/null; then
        log_error "gcloud CLI is not installed"
        exit 1
    fi

    # Check if terraform is installed
    if ! command -v terraform &> /dev/null; then
        log_error "Terraform is not installed"
        exit 1
    fi

    log_info "Requirements check passed"
}

# Build and push Docker images
build_images() {
    log_info "Building Docker images..."

    # Configure Docker for GCR
    gcloud auth configure-docker gcr.io --quiet

    # Build and push agent image
    log_info "Building agent image..."
    docker build -t "gcr.io/${PROJECT_ID}/kintsugi-agent:latest" ./agent-core
    docker push "gcr.io/${PROJECT_ID}/kintsugi-agent:latest"

    # Build and push target app image
    log_info "Building target app image..."
    docker build -t "gcr.io/${PROJECT_ID}/kintsugi-target:latest" ./target-app
    docker push "gcr.io/${PROJECT_ID}/kintsugi-target:latest"

    log_info "Docker images built and pushed"
}

# Deploy infrastructure with Terraform
deploy_infrastructure() {
    log_info "Deploying infrastructure..."

    cd "infrastructure/terraform/environments/${ENVIRONMENT}"

    # Initialize Terraform
    terraform init

    # Create tfvars if not exists
    if [[ ! -f "terraform.tfvars" ]]; then
        log_warn "Creating terraform.tfvars from example..."
        cat > terraform.tfvars << EOF
project_id       = "${PROJECT_ID}"
region           = "${REGION}"
agent_image      = "gcr.io/${PROJECT_ID}/kintsugi-agent:latest"
target_app_image = "gcr.io/${PROJECT_ID}/kintsugi-target:latest"
EOF
    fi

    # Plan and apply
    terraform plan -out=tfplan
    terraform apply tfplan

    cd - > /dev/null

    log_info "Infrastructure deployed"
}

# Main
main() {
    log_info "Starting Kintsugi-Helix deployment..."
    log_info "Project: ${PROJECT_ID}"
    log_info "Region: ${REGION}"
    log_info "Environment: ${ENVIRONMENT}"

    check_requirements
    build_images
    deploy_infrastructure

    log_info "Deployment complete!"

    # Print service URLs
    cd "infrastructure/terraform/environments/${ENVIRONMENT}"
    echo ""
    log_info "Service URLs:"
    echo "  Target App: $(terraform output -raw target_app_url 2>/dev/null || echo 'N/A')"
    echo "  Agent:      $(terraform output -raw agent_url 2>/dev/null || echo 'N/A')"
    cd - > /dev/null
}

main "$@"
