terraform {
  # See canonical/charmed-temporal-solutions#9 for compatibility testing
  # and rationale for the minimum supported version
  required_version = ">= 1.6.6"
  required_providers {
    juju = {
      source  = "juju/juju"
      version = ">= 1.0.0"
    }
  }
}
