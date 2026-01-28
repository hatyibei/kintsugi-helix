# Cloud Logging module for Kintsugi-Helix

variable "project_id" {
  description = "GCP Project ID"
  type        = string
}

variable "log_sink_name" {
  description = "Name for the log sink"
  type        = string
  default     = "kintsugi-error-sink"
}

variable "filter" {
  description = "Log filter expression"
  type        = string
  default     = "severity>=ERROR"
}

variable "pubsub_topic_name" {
  description = "Name for the Pub/Sub topic"
  type        = string
  default     = "kintsugi-error-logs"
}

# Pub/Sub topic for error logs
resource "google_pubsub_topic" "error_logs" {
  name    = var.pubsub_topic_name
  project = var.project_id

  labels = {
    environment = "kintsugi"
    purpose     = "error-aggregation"
  }
}

# Pub/Sub subscription for the agent
resource "google_pubsub_subscription" "agent_subscription" {
  name    = "${var.pubsub_topic_name}-agent-sub"
  topic   = google_pubsub_topic.error_logs.id
  project = var.project_id

  ack_deadline_seconds = 60

  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "600s"
  }

  expiration_policy {
    ttl = "" # Never expire
  }

  labels = {
    environment = "kintsugi"
  }
}

# Log sink to route errors to Pub/Sub
resource "google_logging_project_sink" "error_sink" {
  name        = var.log_sink_name
  project     = var.project_id
  destination = "pubsub.googleapis.com/${google_pubsub_topic.error_logs.id}"
  filter      = var.filter

  unique_writer_identity = true
}

# Grant the log sink permission to publish to Pub/Sub
resource "google_pubsub_topic_iam_member" "sink_publisher" {
  project = var.project_id
  topic   = google_pubsub_topic.error_logs.name
  role    = "roles/pubsub.publisher"
  member  = google_logging_project_sink.error_sink.writer_identity
}

# Log-based metric for error rate monitoring
resource "google_logging_metric" "error_rate" {
  name    = "kintsugi-error-rate"
  project = var.project_id
  filter  = var.filter

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"
    labels {
      key         = "service"
      value_type  = "STRING"
      description = "The service generating the error"
    }
  }

  label_extractors = {
    "service" = "EXTRACT(resource.labels.service_name)"
  }
}

output "topic_id" {
  value = google_pubsub_topic.error_logs.id
}

output "subscription_id" {
  value = google_pubsub_subscription.agent_subscription.id
}

output "sink_writer_identity" {
  value = google_logging_project_sink.error_sink.writer_identity
}
