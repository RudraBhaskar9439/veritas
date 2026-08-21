output "snapshot_bucket" {
  value       = google_storage_bucket.snapshots.name
  description = "Immutable evidence and pre-repair snapshot bucket."
}

output "workspace_event_topic" {
  value       = google_pubsub_topic.workspace_events.id
  description = "Canonical Workspace event topic."
}

output "repair_queue" {
  value       = google_cloud_tasks_queue.repairs.id
  description = "Durable per-artifact repair command queue."
}

output "database_connection_name" {
  value       = google_sql_database_instance.postgres.connection_name
  description = "Cloud SQL connection name for runtime services."
}

output "credential_kms_key" {
  value       = google_kms_crypto_key.credentials.id
  description = "Cloud KMS key that encrypts Google Workspace credential envelopes."
}

output "auth_secret_ids" {
  value       = { for name, secret in google_secret_manager_secret.auth : name => secret.secret_id }
  description = "Secret Manager IDs populated out-of-band during the Phase 2 live gate."
}

output "deployed_service_uris" {
  value       = { for name, service in google_cloud_run_v2_service.runtime : name => service.uri }
  description = "Cloud Run service URIs when immutable images are supplied."
}
