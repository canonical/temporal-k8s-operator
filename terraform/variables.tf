variable "name" {
  type        = string
  description = "Name of the deployed application"
  default     = "temporal-k8s"
}

variable "units" {
  type        = number
  description = "Number of units to deploy with this name and configuration"
  default     = 1
}

variable "model" {
  type        = string
  description = "Juju model where the application is to be deployed"
}

variable "revision" {
  type        = number
  description = "Revision of the charm to deploy"
  default     = 55
}

variable "channel" {
  type        = string
  description = "Charmhub channel to deploy the charm from"
  default     = "1.23/edge" # TODO: change to 1.23/stable
}

variable "services" {
  type = string
  description = "Comma separated list of Temporal services to run"
  default = "frontend,history,matching,worker"
}

variable "num_history_shards" {
  type = number
  description = "Number of concurrent database operations that can occur for a Temporal Cluster"
  default = 1
}

variable "external_hostname" {
  type = string
  description = "The DNS listing used for external connections"
  default = ""
}

variable "log_level" {
  type = string
  description = "Temporal server logging level"
  default = "info"
}

variable "tls_secret_name" {
  type = string
  description = "Name of the k8s secret which contains the TLS certificate to be used by ingress"
  default = "temporal-tls"
}

variable "auth" {
  type = object({
    enabled                = optional(bool)
    google_client_id       = optional(string)
    admin_groups           = optional(string)
    open_access_namespaces = optional(string)
  })
  description = "Authentication related configurations"
  default = {
    enabled                = false
    google_client_id       = ""
    admin_groups           = ""
    open_access_namespaces = ""
  }
}

variable "persistence" {
  type = object({
    max_connections      = optional(number),
    max_idle_connections = optional(number),
    max_connection_time  = optional(string),
  })
  description = "Persistence database configurations"
  default = {
    max_connections      = 20,
    max_idle_connections = 20,
    max_connection_time  = "1h"
  }
}

variable "visibility" {
  type = object({
    max_connections      = optional(number),
    max_idle_connections = optional(number),
    max_connection_time  = optional(string),
  })
  description = "Visibility database configurations"
  default = {
    max_connections      = 10,
    max_idle_connections = 10,
    max_connection_time  = "1h"
  }
}

variable "global_rps_limit" {
  type        = number
  description = "Global limit for requests per second per namespace"
  default     = 2000
}

variable "namespace_rps_limit" {
  type        = string
  description = "Pipe-separated definition of namespace requests per second limits"
  default     = ""
}

variable "long_poll_interval" {
  type        = string
  description = "The long poll expiration interval in the matching service"
  default     = "50s"
}

variable "frontend_cert" {
  type = object({
    common_name = optional(string),
    sans_dns    = optional(string)
  })
  description = "Frontend certitifactes related configuration"
  default = {
    common_name = "",
    sans_dns    = ""
  }
}
