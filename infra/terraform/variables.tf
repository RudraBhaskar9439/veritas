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

variable "google_oauth_redirect_uri" {
  description = "Exact HTTPS Google OAuth callback exposed by the public web origin."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition     = var.google_oauth_redirect_uri == null || can(regex("^https://[^/]+/api/v1/auth/google/callback$", var.google_oauth_redirect_uri))
    error_message = "google_oauth_redirect_uri must be null or an HTTPS /api/v1/auth/google/callback URL"
  }
}

variable "drive_webhook_url" {
  description = "Exact HTTPS Drive notification endpoint for the deployed ingress service."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition     = var.drive_webhook_url == null || can(regex("^https://[^/]+/api/v1/integrations/google-drive/notifications$", var.drive_webhook_url))
    error_message = "drive_webhook_url must be null or the HTTPS Drive notification endpoint"
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

variable "budget_currency_code" {
  description = "ISO 4217 currency code of the billing account used for the warning budget."
  type        = string
  default     = "USD"

  validation {
    condition     = can(regex("^[A-Z]{3}$", var.budget_currency_code))
    error_message = "budget_currency_code must be a three-letter uppercase ISO 4217 currency code"
  }
}

variable "monthly_budget_amount" {
  description = "Gross monthly amount that triggers preview warnings in budget_currency_code; this budget does not itself cap spending."
  type        = number
  default     = 50

  validation {
    condition     = var.monthly_budget_amount >= 1 && var.monthly_budget_amount <= 1000000 && floor(var.monthly_budget_amount) == var.monthly_budget_amount
    error_message = "monthly_budget_amount must be a positive whole-currency amount no greater than 1,000,000"
  }
}
