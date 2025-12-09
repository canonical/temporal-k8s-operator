variable "app_name" {
  type        = string
  description = "Name of the deployed application"
  default     = "temporal-k8s"
}

variable "units" {
  type        = number
  description = "Number of units to deploy with this name and configuration"
  default     = 1
}

variable "model_uuid" {
  type        = string
  description = "UUID of Juju model where the application is to be deployed"
}

variable "revision" {
  type        = number
  description = "Revision of the charm to deploy"
  default     = null
}

variable "channel" {
  type        = string
  description = "Charmhub channel to deploy the charm from"
  default     = "1.23/stable"
}

variable "constraints" {
  type        = string
  description = "Constraints to be used when deploying this application"
  default     = "arch=amd64"
}

variable "config" {
  type        = map(string)
  description = "Configurations to deploy this application with"
  default     = {}
}
