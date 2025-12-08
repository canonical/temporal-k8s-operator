resource "juju_application" "temporal_k8s" {
  name       = var.app_name
  model_uuid = var.model_uuid

  charm {
    name     = "temporal-k8s"
    revision = var.revision
    channel  = var.channel
  }

  constraints = var.constraints
  config      = var.config

  units = var.units
}
