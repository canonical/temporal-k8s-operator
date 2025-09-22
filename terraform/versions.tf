terraform {
  required_version = ">= 1.12.2"
  required_providers {
    juju = {
      source  = "juju/juju"
      version = ">= 0.21.1"
    }
  }
}
