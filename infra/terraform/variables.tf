variable "project_id" {
  description = "Google Cloud project that hosts Veritas."
  type        = string
}

variable "region" {
  description = "Primary single region for ordered processing and data residency."
  type        = string
  default     = "us-central1"
}

variable "environment" {
  description = "Deployment environment."
  type        = string
  default     = "preview"

  validation {
    condition     = contains(["preview", "production"], var.environment)
    error_message = "environment must be preview or production"
  }
}

variable "service_images" {
  description = "Optional immutable container image per deployable service. Empty during foundation bootstrap."
  type        = map(string)
  default     = {}

  validation {
    condition     = alltrue([for name in keys(var.service_images) : contains(["api", "ingress", "worker", "web"], name)])
    error_message = "service_images keys must be api, ingress, worker, or web"
  }
}

variable "database_tier" {
  description = "Cloud SQL machine tier."
  type        = string
  default     = "db-f1-micro"
}

