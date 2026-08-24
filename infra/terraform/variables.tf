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

variable "billing_account_id" {
  description = "Optional Cloud Billing account ID used for the project-scoped gross-cost warning budget."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition     = var.billing_account_id == null || can(regex("^[0-9A-F]{6}-[0-9A-F]{6}-[0-9A-F]{6}$", var.billing_account_id))
    error_message = "billing_account_id must be null or a Google Cloud Billing account ID such as 000000-000000-000000"
  }
}

variable "monthly_budget_usd" {
  description = "Gross monthly cost that triggers preview warnings; this budget does not itself cap spending."
  type        = number
  default     = 50

  validation {
    condition     = var.monthly_budget_usd >= 5 && var.monthly_budget_usd <= 300 && floor(var.monthly_budget_usd) == var.monthly_budget_usd
    error_message = "monthly_budget_usd must be a whole-dollar amount between 5 and 300"
  }
}
