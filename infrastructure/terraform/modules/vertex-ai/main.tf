# Vertex AI module for Kintsugi-Helix

variable "project_id" {
  description = "GCP Project ID"
  type        = string
}

variable "region" {
  description = "GCP Region"
  type        = string
  default     = "us-central1"
}

variable "service_account_email" {
  description = "Service account email for Vertex AI access"
  type        = string
}

# Enable required APIs
resource "google_project_service" "vertex_ai" {
  project = var.project_id
  service = "aiplatform.googleapis.com"

  disable_dependent_services = false
  disable_on_destroy         = false
}

resource "google_project_service" "generative_ai" {
  project = var.project_id
  service = "generativelanguage.googleapis.com"

  disable_dependent_services = false
  disable_on_destroy         = false
}

# IAM binding for Vertex AI User role
resource "google_project_iam_member" "vertex_ai_user" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${var.service_account_email}"
}

# IAM binding for Generative AI access
resource "google_project_iam_member" "generative_ai_user" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${var.service_account_email}"
}

# Optional: Create a Vertex AI Workbench instance for development
variable "create_workbench" {
  description = "Whether to create a Workbench instance"
  type        = bool
  default     = false
}

resource "google_workbench_instance" "kintsugi_dev" {
  count    = var.create_workbench ? 1 : 0
  name     = "kintsugi-dev-workbench"
  location = "${var.region}-a"
  project  = var.project_id

  gce_setup {
    machine_type = "n1-standard-4"

    boot_disk {
      disk_size_gb = 100
      disk_type    = "PD_SSD"
    }

    service_accounts {
      email = var.service_account_email
    }
  }

  depends_on = [google_project_service.vertex_ai]
}

output "vertex_ai_enabled" {
  value = true
}

output "region" {
  value = var.region
}
