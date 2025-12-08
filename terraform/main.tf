data "juju_model" "terraform_model" {
  name  = var.model
  owner = "admin"
}

resource "juju_application" "temporal_k8s" {
  name       = var.app_name
  model_uuid = data.juju_model.terraform_model.uuid

  charm {
    name     = "temporal-k8s"
    revision = var.revision
    channel  = var.channel
  }

  constraints = var.constraints
  config      = var.config

  units = var.units
}
