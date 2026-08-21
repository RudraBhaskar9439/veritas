locals {
  name = "veritas-${var.environment}"

  required_services = toset([
    "aiplatform.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudkms.googleapis.com",
    "cloudtasks.googleapis.com",
    "docs.googleapis.com",
    "drive.googleapis.com",
    "gmail.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
    "pubsub.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "sheets.googleapis.com",
    "slides.googleapis.com",
    "sqladmin.googleapis.com",
    "tasks.googleapis.com",
    "cloudtrace.googleapis.com",
  ])

  service_accounts = toset(["api", "ingress", "worker"])
}

resource "google_project_service" "required" {
  for_each = local.required_services

  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_service_account" "runtime" {
  for_each = local.service_accounts

  account_id   = "${local.name}-${each.key}"
  display_name = "Veritas ${var.environment} ${each.key}"
  depends_on   = [google_project_service.required]
}

resource "google_artifact_registry_repository" "containers" {
  location      = var.region
  repository_id = "${local.name}-containers"
  description   = "Immutable Veritas service images"
  format        = "DOCKER"
  depends_on    = [google_project_service.required]
}

resource "google_storage_bucket" "snapshots" {
  name                        = "${var.project_id}-${local.name}-snapshots"
  location                    = var.region
  uniform_bucket_level_access = true
  force_destroy               = false

  versioning {
    enabled = true
  }

  lifecycle_rule {
    condition {
      age = 30
    }
    action {
      type = "SetStorageClass"
      storage_class = "NEARLINE"
    }
  }
}

resource "google_pubsub_topic" "workspace_events" {
  name       = "${local.name}-workspace-events"
  depends_on = [google_project_service.required]
}

resource "google_pubsub_topic" "dead_letter" {
  name       = "${local.name}-dead-letter"
  depends_on = [google_project_service.required]
}

resource "google_pubsub_subscription" "orchestrator" {
  name  = "${local.name}-orchestrator"
  topic = google_pubsub_topic.workspace_events.id

  ack_deadline_seconds       = 60
  message_retention_duration = "604800s"

  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "600s"
  }

  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.dead_letter.id
    max_delivery_attempts = 10
  }
}

resource "google_cloud_tasks_queue" "repairs" {
  name     = "${local.name}-repairs"
  location = var.region

  rate_limits {
    max_concurrent_dispatches = 10
    max_dispatches_per_second = 5
  }

  retry_config {
    max_attempts       = 8
    max_retry_duration = "3600s"
    min_backoff        = "5s"
    max_backoff        = "300s"
    max_doublings      = 5
  }

  depends_on = [google_project_service.required]
}

resource "google_kms_key_ring" "veritas" {
  name       = local.name
  location   = var.region
  depends_on = [google_project_service.required]
}

resource "google_kms_crypto_key" "credentials" {
  name            = "workspace-credentials"
  key_ring        = google_kms_key_ring.veritas.id
  rotation_period = "7776000s"

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_secret_manager_secret" "oauth_client" {
  secret_id = "${local.name}-google-oauth-client"

  replication {
    auto {}
  }

  depends_on = [google_project_service.required]
}

resource "google_sql_database_instance" "postgres" {
  name             = "${local.name}-postgres"
  database_version = "POSTGRES_16"
  region           = var.region

  settings {
    tier              = var.database_tier
    availability_type = var.environment == "production" ? "REGIONAL" : "ZONAL"
    disk_autoresize   = true
    disk_type         = "PD_SSD"
    disk_size         = 10

    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = true
    }

    ip_configuration {
      ipv4_enabled = true
      require_ssl  = true
    }

    database_flags {
      name  = "cloudsql.iam_authentication"
      value = "on"
    }
  }

  deletion_protection = var.environment == "production"
  depends_on          = [google_project_service.required]
}

resource "google_sql_database" "veritas" {
  name     = "veritas"
  instance = google_sql_database_instance.postgres.name
}

resource "google_cloud_run_v2_service" "runtime" {
  for_each = var.service_images

  name     = "${local.name}-${each.key}"
  location = var.region

  template {
    service_account = each.key == "web" ? google_service_account.runtime["api"].email : google_service_account.runtime[each.key].email
    timeout         = "300s"

    scaling {
      min_instance_count = 0
      max_instance_count = each.key == "worker" ? 20 : 5
    }

    containers {
      image = each.value

      env {
        name  = "VERITAS_ENVIRONMENT"
        value = var.environment
      }

      env {
        name  = "VERITAS_VERSION"
        value = "0.1.0"
      }
    }
  }

  depends_on = [google_project_service.required]
}

resource "google_storage_bucket_iam_member" "worker_snapshots" {
  bucket = google_storage_bucket.snapshots.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.runtime["worker"].email}"
}

resource "google_kms_crypto_key_iam_member" "api_credentials" {
  crypto_key_id = google_kms_crypto_key.credentials.id
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = "serviceAccount:${google_service_account.runtime["api"].email}"
}

resource "google_secret_manager_secret_iam_member" "api_oauth_client" {
  secret_id = google_secret_manager_secret.oauth_client.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime["api"].email}"
}

resource "google_project_iam_member" "worker_roles" {
  for_each = toset([
    "roles/aiplatform.user",
    "roles/cloudsql.client",
    "roles/cloudtasks.enqueuer",
    "roles/pubsub.subscriber",
  ])

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.runtime["worker"].email}"
}

