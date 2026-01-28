# Development environment for Kintsugi-Helix

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }

  # Backend configuration - uncomment and configure for remote state
  # backend "gcs" {
  #   bucket = "kintsugi-terraform-state"
  #   prefix = "dev"
  # }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

variable "project_id" {
  description = "GCP Project ID"
  type        = string
}

variable "region" {
  description = "GCP Region"
  type        = string
  default     = "us-central1"
}

variable "agent_image" {
  description = "Container image for the Kintsugi agent"
  type        = string
  default     = "gcr.io/PROJECT_ID/kintsugi-agent:latest"
}

variable "target_app_image" {
  description = "Container image for the target application"
  type        = string
  default     = "gcr.io/PROJECT_ID/kintsugi-target:latest"
}

# Enable required APIs
resource "google_project_service" "required_apis" {
  for_each = toset([
    "run.googleapis.com",
    "logging.googleapis.com",
    "pubsub.googleapis.com",
    "aiplatform.googleapis.com",
    "cloudbuild.googleapis.com",
    "artifactregistry.googleapis.com",
  ])

  project = var.project_id
  service = each.value

  disable_dependent_services = false
  disable_on_destroy         = false
}

# Cloud Logging module
module "logging" {
  source = "../../modules/logging"

  project_id        = var.project_id
  log_sink_name     = "kintsugi-dev-error-sink"
  pubsub_topic_name = "kintsugi-dev-errors"
  filter            = "severity>=ERROR AND resource.type=\"cloud_run_revision\""

  depends_on = [google_project_service.required_apis]
}

# Target Application (Cloud Run)
module "target_app" {
  source = "../../modules/cloud-run"

  project_id   = var.project_id
  region       = var.region
  service_name = "kintsugi-target-app-dev"
  image        = var.target_app_image

  env_vars = {
    SPRING_PROFILES_ACTIVE = "dev"
    LOG_LEVEL              = "DEBUG"
  }

  min_instances = 0
  max_instances = 3
  memory        = "512Mi"
  cpu           = "1"

  depends_on = [google_project_service.required_apis]
}

# Kintsugi Agent (Cloud Run)
module "agent" {
  source = "../../modules/cloud-run"

  project_id   = var.project_id
  region       = var.region
  service_name = "kintsugi-agent-dev"
  image        = var.agent_image

  env_vars = {
    GOOGLE_CLOUD_PROJECT  = var.project_id
    VERTEX_AI_LOCATION    = var.region
    LOG_FILTER            = "severity>=ERROR"
    AUTO_MERGE_THRESHOLD  = "0.3"
    DRY_RUN               = "true"
    MODE                  = "dev"
  }

  min_instances = 0
  max_instances = 2
  memory        = "1Gi"
  cpu           = "2"

  depends_on = [google_project_service.required_apis]
}

# Vertex AI module
module "vertex_ai" {
  source = "../../modules/vertex-ai"

  project_id            = var.project_id
  region                = var.region
  service_account_email = module.agent.service_account_email
  create_workbench      = false

  depends_on = [module.agent]
}

# Grant agent access to logs
resource "google_project_iam_member" "agent_logging" {
  project = var.project_id
  role    = "roles/logging.viewer"
  member  = "serviceAccount:${module.agent.service_account_email}"
}

# Grant agent access to Pub/Sub
resource "google_pubsub_subscription_iam_member" "agent_subscriber" {
  project      = var.project_id
  subscription = module.logging.subscription_id
  role         = "roles/pubsub.subscriber"
  member       = "serviceAccount:${module.agent.service_account_email}"
}

# Outputs
output "target_app_url" {
  description = "URL of the target application"
  value       = module.target_app.service_url
}

output "agent_url" {
  description = "URL of the Kintsugi agent"
  value       = module.agent.service_url
}

output "error_topic_id" {
  description = "Pub/Sub topic for error logs"
  value       = module.logging.topic_id
}
