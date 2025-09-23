output "app_name" {
  value = juju_application.temporal_k8s.name
}

output "provides" {
  value = {
    metrics_endpoint  = "metrics-endpoint"
    grafana_dashboard = "grafana-dashboard"
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
  }
}
