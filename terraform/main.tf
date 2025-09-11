resource "juju_application" "temporal_k8s" {
  name  = var.name
  model = var.model

  charm {
    name     = "temporal-k8s"
    revision = var.revision
    channel  = var.channel
  }

  config = {
    services           = var.services
    num-history-shards = var.num_history_shards
    external-hostname  = var.external_hostname

    log-level = var.log_level

    tls-secret-name = var.tls_secret_name

    auth-enabled                = var.auth["enabled"]
    auth-google-client-id       = var.auth["google_client_id"]
    auth-admin-groups           = var.auth["admin_groups"]
    auth-open-access-namespaces = var.auth["open_access_namespaces"]

    persistence-max-conns      = var.persistence["max_connections"]
    persistence-max-idle-conns = var.persistence["max_idle_connections"]
    persistence-max-conn-time  = var.persistence["max_connection_time"]

    visibility-max-conns      = var.visibility["max_connections"]
    visibility-max-idle-conns = var.visibility["max_idle_connections"]
    visibility-max-conn-time  = var.visibility["max_connection_time"]

    global-rps-limit    = var.global_rps_limit
    namespace-rps-limit = var.namespace_rps_limit
    long-poll-interval  = var.long_poll_interval

    frontend-cert-common-name = var.frontend_cert["common_name"]
    frontend-cert-sans-dns    = var.frontend_cert["sans_dns"]
  }

  units = var.units
}
