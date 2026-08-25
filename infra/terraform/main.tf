locals {
  name = "veritas-${var.environment}"

  required_services = toset([
    "aiplatform.googleapis.com",
    "artifactregistry.googleapis.com",
    "billingbudgets.googleapis.com",
    "cloudkms.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "cloudscheduler.googleapis.com",
    "cloudtasks.googleapis.com",
    "docs.googleapis.com",
    "drive.googleapis.com",
    "gmail.googleapis.com",
    "iam.googleapis.com",
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

  service_accounts          = toset(["api", "ingress", "migrator", "worker", "web"])
  database_service_accounts = toset(["api", "ingress", "migrator", "worker"])

  runtime_entrypoints = {
    api     = "veritas_runtime.api:app"
    ingress = "veritas_runtime.ingress:app"
    worker  = "veritas_runtime.worker:app"
  }

  deterministic_service_urls = {
    api     = "https://${local.name}-api-${data.google_project.current.number}.${var.region}.run.app"
    ingress = "https://${local.name}-ingress-${data.google_project.current.number}.${var.region}.run.app"
    worker  = "https://${local.name}-worker-${data.google_project.current.number}.${var.region}.run.app"
    web     = "https://${local.name}-web-${data.google_project.current.number}.${var.region}.run.app"
  }

  google_oauth_redirect_uri = coalesce(
    var.google_oauth_redirect_uri,
    "${local.deterministic_service_urls.web}/api/v1/auth/google/callback",
  )
  drive_webhook_url = coalesce(
    var.drive_webhook_url,
    "${local.deterministic_service_urls.ingress}/api/v1/integrations/google-drive/notifications",
  )

  runtime_max_instances = var.environment == "production" ? {
    api     = 5
    ingress = 5
    worker  = 20
    web     = 5
    } : {
    api     = 2
    ingress = 2
    worker  = 3
    web     = 2
  }

  api_auth_secrets = toset([
    "application-session-key",
    "drive-channel-token-key",
    "google-oauth-client-id",
    "google-oauth-client-secret",
    "oauth-ticket-key",
  ])

  auth_secrets = setunion(local.api_auth_secrets, toset([
    "drive-channel-token-key",
  ]))
}

data "google_project" "current" {
  project_id = var.project_id
}

resource "google_billing_budget" "preview" {
  count = var.billing_account_id == null ? 0 : 1

  billing_account = var.billing_account_id
  display_name    = "${local.name}: gross-cost warning budget"

  budget_filter {
    calendar_period        = "MONTH"
    projects               = ["projects/${data.google_project.current.number}"]
    credit_types_treatment = "EXCLUDE_ALL_CREDITS"
  }

  amount {
    specified_amount {
      currency_code = var.budget_currency_code
      units         = tostring(var.monthly_budget_amount)
    }
  }

  dynamic "threshold_rules" {
    for_each = toset([0.2, 0.5, 0.8, 1.0])
    content {
      threshold_percent = threshold_rules.value
      spend_basis       = "CURRENT_SPEND"
    }
  }

  depends_on = [google_project_service.required]
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
      type          = "SetStorageClass"
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

resource "google_secret_manager_secret" "auth" {
  for_each = local.auth_secrets

  secret_id = "${local.name}-${each.key}"

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
    edition               = "ENTERPRISE"
    tier                  = var.database_tier
    availability_type     = var.environment == "production" ? "REGIONAL" : "ZONAL"
    disk_autoresize       = true
    disk_autoresize_limit = var.environment == "production" ? 100 : 20
    disk_type             = "PD_SSD"
    disk_size             = 10

    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = true
    }

    ip_configuration {
      ipv4_enabled = true
      ssl_mode     = "ENCRYPTED_ONLY"
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

resource "google_sql_user" "runtime_iam" {
  for_each = local.database_service_accounts

  name     = trimsuffix(google_service_account.runtime[each.key].email, ".gserviceaccount.com")
  instance = google_sql_database_instance.postgres.name
  type     = "CLOUD_IAM_SERVICE_ACCOUNT"
}

resource "google_cloud_run_v2_service" "runtime" {
  for_each = var.service_images

  name     = "${local.name}-${each.key}"
  location = var.region
  ingress  = each.key == "worker" ? "INGRESS_TRAFFIC_INTERNAL_ONLY" : "INGRESS_TRAFFIC_ALL"

  deletion_protection = var.environment == "production"

  template {
    service_account                  = google_service_account.runtime[each.key].email
    timeout                          = "300s"
    max_instance_request_concurrency = each.key == "worker" ? 1 : 40

    scaling {
      min_instance_count = 0
      max_instance_count = local.runtime_max_instances[each.key]
    }

    containers {
      image = each.value

      command = each.key == "web" ? null : ["uvicorn"]
      args = each.key == "web" ? null : [
        local.runtime_entrypoints[each.key],
        "--host",
        "0.0.0.0",
        "--port",
        "8080",
        "--no-access-log",
      ]

      resources {
        cpu_idle = true
        limits = {
          cpu    = "1"
          memory = each.key == "worker" ? "1Gi" : "512Mi"
        }
      }

      env {
        name  = "VERITAS_ENVIRONMENT"
        value = var.environment
      }

      env {
        name  = "VERITAS_VERSION"
        value = "0.1.0"
      }

      dynamic "env" {
        for_each = each.key == "web" ? {} : {
          VERITAS_CLOUD_SQL_INSTANCE = google_sql_database_instance.postgres.connection_name
          VERITAS_CLOUD_SQL_DATABASE = google_sql_database.veritas.name
          VERITAS_CLOUD_SQL_USER     = trimsuffix(google_service_account.runtime[each.key].email, ".gserviceaccount.com")
        }
        content {
          name  = env.key
          value = env.value
        }
      }

      dynamic "env" {
        for_each = each.key == "web" ? {
          VERITAS_API_ORIGIN = local.deterministic_service_urls.api
        } : {}
        content {
          name  = env.key
          value = env.value
        }
      }

      dynamic "env" {
        for_each = contains(["api", "worker"], each.key) ? {
          VERITAS_GOOGLE_KMS_CREDENTIALS_KEY = google_kms_crypto_key.credentials.id
          VERITAS_SNAPSHOT_BUCKET            = google_storage_bucket.snapshots.name
        } : {}
        content {
          name  = env.key
          value = env.value
        }
      }

      dynamic "env" {
        for_each = each.key == "worker" ? {
          VERITAS_GOOGLE_CLOUD_PROJECT  = var.project_id
          VERITAS_GOOGLE_CLOUD_LOCATION = var.region
          VERITAS_GEMINI_MODEL          = "gemini-2.5-flash"
        } : {}
        content {
          name  = env.key
          value = env.value
        }
      }

      dynamic "env" {
        for_each = contains(["api", "worker"], each.key) ? {
          VERITAS_GOOGLE_OAUTH_REDIRECT_URI = local.google_oauth_redirect_uri
        } : {}
        content {
          name  = env.key
          value = env.value
        }
      }

      dynamic "env" {
        for_each = contains(["api", "ingress"], each.key) ? {
          VERITAS_DRIVE_WEBHOOK_URL = local.drive_webhook_url
        } : {}
        content {
          name  = env.key
          value = env.value
        }
      }

      dynamic "env" {
        for_each = each.key == "api" ? {
          VERITAS_APPLICATION_SESSION_KEY    = google_secret_manager_secret.auth["application-session-key"].secret_id
          VERITAS_DRIVE_CHANNEL_TOKEN_KEY    = google_secret_manager_secret.auth["drive-channel-token-key"].secret_id
          VERITAS_GOOGLE_OAUTH_CLIENT_ID     = google_secret_manager_secret.auth["google-oauth-client-id"].secret_id
          VERITAS_GOOGLE_OAUTH_CLIENT_SECRET = google_secret_manager_secret.auth["google-oauth-client-secret"].secret_id
          VERITAS_OAUTH_TICKET_KEY           = google_secret_manager_secret.auth["oauth-ticket-key"].secret_id
          } : each.key == "worker" ? {
          VERITAS_GOOGLE_OAUTH_CLIENT_ID     = google_secret_manager_secret.auth["google-oauth-client-id"].secret_id
          VERITAS_GOOGLE_OAUTH_CLIENT_SECRET = google_secret_manager_secret.auth["google-oauth-client-secret"].secret_id
          VERITAS_OAUTH_TICKET_KEY           = google_secret_manager_secret.auth["oauth-ticket-key"].secret_id
          } : each.key == "ingress" ? {
          VERITAS_DRIVE_CHANNEL_TOKEN_KEY = google_secret_manager_secret.auth["drive-channel-token-key"].secret_id
        } : {}
        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = env.value
              version = "latest"
            }
          }
        }
      }

      startup_probe {
        initial_delay_seconds = 1
        timeout_seconds       = 3
        period_seconds        = 5
        failure_threshold     = 12
        http_get {
          path = "/health/ready"
        }
      }

      liveness_probe {
        timeout_seconds   = 3
        period_seconds    = 30
        failure_threshold = 3
        http_get {
          path = "/health/live"
        }
      }
    }
  }

  depends_on = [google_project_service.required]
}

resource "google_cloud_run_v2_job" "migrations" {
  count = contains(keys(var.service_images), "worker") ? 1 : 0

  name                = "${local.name}-migrations"
  location            = var.region
  deletion_protection = var.environment == "production"

  template {
    template {
      service_account = google_service_account.runtime["migrator"].email
      timeout         = "900s"
      max_retries     = 0

      containers {
        image   = var.service_images["worker"]
        command = ["python", "-m", "veritas_runtime.migrations"]

        resources {
          limits = {
            cpu    = "1"
            memory = "512Mi"
          }
        }

        env {
          name  = "VERITAS_ENVIRONMENT"
          value = var.environment
        }

        env {
          name  = "VERITAS_CLOUD_SQL_INSTANCE"
          value = google_sql_database_instance.postgres.connection_name
        }

        env {
          name  = "VERITAS_CLOUD_SQL_DATABASE"
          value = google_sql_database.veritas.name
        }

        env {
          name  = "VERITAS_CLOUD_SQL_USER"
          value = trimsuffix(google_service_account.runtime["migrator"].email, ".gserviceaccount.com")
        }
      }
    }
  }

  depends_on = [google_project_service.required]
}

resource "google_storage_bucket_iam_member" "worker_snapshot_create" {
  bucket = google_storage_bucket.snapshots.name
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${google_service_account.runtime["worker"].email}"
}

resource "google_storage_bucket_iam_member" "worker_snapshot_read" {
  bucket = google_storage_bucket.snapshots.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.runtime["worker"].email}"
}

resource "google_storage_bucket_iam_member" "api_snapshot_read" {
  bucket = google_storage_bucket.snapshots.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.runtime["api"].email}"
}

resource "google_kms_crypto_key_iam_member" "api_credentials" {
  crypto_key_id = google_kms_crypto_key.credentials.id
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = "serviceAccount:${google_service_account.runtime["api"].email}"
}

resource "google_kms_crypto_key_iam_member" "worker_credentials" {
  crypto_key_id = google_kms_crypto_key.credentials.id
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = "serviceAccount:${google_service_account.runtime["worker"].email}"
}

resource "google_secret_manager_secret_iam_member" "api_auth" {
  for_each = {
    for name, secret in google_secret_manager_secret.auth : name => secret
    if contains(local.api_auth_secrets, name)
  }

  secret_id = each.value.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime["api"].email}"
}

resource "google_secret_manager_secret_iam_member" "worker_auth" {
  for_each = {
    for name, secret in google_secret_manager_secret.auth : name => secret
    if contains(["google-oauth-client-id", "google-oauth-client-secret", "oauth-ticket-key"], name)
  }

  secret_id = each.value.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime["worker"].email}"
}

resource "google_secret_manager_secret_iam_member" "ingress_channel_token" {
  secret_id = google_secret_manager_secret.auth["drive-channel-token-key"].id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime["ingress"].email}"
}

resource "google_project_iam_member" "api_cloudsql" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.runtime["api"].email}"
}

resource "google_project_iam_member" "migrator_cloudsql" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.runtime["migrator"].email}"
}

resource "google_project_iam_member" "runtime_cloudsql_instance_user" {
  for_each = local.database_service_accounts

  project = var.project_id
  role    = "roles/cloudsql.instanceUser"
  member  = "serviceAccount:${google_service_account.runtime[each.key].email}"
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

resource "google_project_iam_member" "ingress_roles" {
  for_each = toset([
    "roles/cloudsql.client",
    "roles/pubsub.publisher",
  ])

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.runtime["ingress"].email}"
}

resource "google_logging_metric" "operation_dead_letters" {
  name        = "${local.name}-operation-dead-letters"
  description = "Veritas operations quarantined after permanent or exhausted failures."
  filter      = "resource.type=\"cloud_run_revision\" AND jsonPayload.event=\"operation.dead_lettered\""

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"
  }

  depends_on = [google_project_service.required]
}

resource "google_logging_metric" "operation_retries" {
  name        = "${local.name}-operation-retries"
  description = "Veritas operations scheduled for bounded retry."
  filter      = "resource.type=\"cloud_run_revision\" AND jsonPayload.event=\"operation.retry_scheduled\""

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"
  }

  depends_on = [google_project_service.required]
}

resource "google_monitoring_alert_policy" "operation_dead_letter" {
  display_name = "${local.name}: operation entered dead letter quarantine"
  combiner     = "OR"

  conditions {
    display_name = "At least one operation was quarantined"

    condition_threshold {
      filter          = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.operation_dead_letters.name}\" AND resource.type=\"cloud_run_revision\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "0s"

      aggregations {
        alignment_period     = "60s"
        per_series_aligner   = "ALIGN_RATE"
        cross_series_reducer = "REDUCE_SUM"
      }
    }
  }

  alert_strategy {
    auto_close = "1800s"
  }

  documentation {
    content   = "Inspect the dead-letter operation by correlation ID, correct the dependency, then use audited replay. Never mutate the original operation."
    mime_type = "text/markdown"
  }
}

resource "google_cloud_run_v2_service_iam_member" "public" {
  for_each = toset([
    for name in keys(var.service_images) : name
    if contains(["api", "ingress", "web"], name)
  ])

  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.runtime[each.value].name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_run_v2_service_iam_member" "worker_scheduler" {
  count = contains(keys(var.service_images), "worker") ? 1 : 0

  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.runtime["worker"].name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.runtime["worker"].email}"
}

resource "google_cloud_scheduler_job" "worker_tick" {
  count = contains(keys(var.service_images), "worker") ? 1 : 0

  name             = "${local.name}-worker-tick"
  description      = "Drains the transactional Drive outbox and advances durable operations."
  region           = var.region
  schedule         = "* * * * *"
  time_zone        = "Etc/UTC"
  attempt_deadline = "300s"

  retry_config {
    retry_count          = 3
    min_backoff_duration = "5s"
    max_backoff_duration = "60s"
    max_doublings        = 3
  }

  http_target {
    http_method = "POST"
    uri         = "${local.deterministic_service_urls.worker}/internal/v1/operations/tick"
    body        = base64encode(jsonencode({ workerId = "cloud-scheduler" }))
    headers = {
      "Content-Type" = "application/json"
    }

    oidc_token {
      service_account_email = google_service_account.runtime["worker"].email
      audience              = local.deterministic_service_urls.worker
    }
  }

  depends_on = [
    google_cloud_run_v2_service_iam_member.worker_scheduler,
    google_project_service.required,
  ]
}
