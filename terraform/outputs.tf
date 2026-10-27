output "app_name" {
  value = juju_application.temporal_k8s.name
}

output "provides" {
  value = {
    metrics_endpoint            = "metrics-endpoint"
    grafana_dashboard           = "grafana-dashboard"
    temporal_host_info          = "temporal-host-info"
    temporal_external_host_info = "temporal-external-host-info"
  }
}

output "requires" {
  value = {
    admin                 = "admin"
    db                    = "db"
    frontend_certificates = "frontend-certificates"
    visibility            = "visibility"
    nginx_route           = "nginx-route"
    ui                    = "ui"
    logging               = "logging"
    openfga               = "openfga"
    s3_paramaters         = "s3-parameters"
    ingress               = "ingress"
  }
}
