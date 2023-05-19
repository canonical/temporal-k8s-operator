[![Charmhub Badge](https://charmhub.io/temporal-k8s/badge.svg)](https://charmhub.io/temporal-k8s)
[![Release Edge](https://github.com/canonical/temporal-k8s-operator/actions/workflows/test_and_publish_charm.yaml/badge.svg)](https://github.com/canonical/temporal-k8s-operator/actions/workflows/test_and_publish_charm.yaml)

# Temporal K8s Operator

This is the Kubernetes Python Operator for [Temporal](https://temporal.io/).

## Description

Temporal is a developer-first, open source platform that ensures the successful
execution of services and applications (using workflows).

Use Workflow as Code (TM) to build and operate resilient applications. Leverage
developer friendly primitives and avoid fighting your infrastructure

This operator provides a Temporal server, and consists of Python scripts which
wraps the versions distributed by
[temporalio](https://hub.docker.com/r/temporalio/server).

## Usage

Note: This operator requires the use of juju>=3.1.

### Deploying PostgreSQL Database

The Temporal and PostgreSQL operators can be deployed and connected to each
other using the Juju command line as follows:

```bash
juju deploy temporal-k8s
juju deploy postgresql-k8s --channel 14/stable --trust
juju relate temporal-k8s:db postgresql-k8s:database
juju relate temporal-k8s:visibility postgresql-k8s:database
```

### Deploying Temporal Admin

On initial deployment, the Temporal operator requires integration with the
[Temporal Admin operator](https://github.com/canonical/temporal-admin-k8s-operator)
for schema creation. Once the Temporal Admin operator is deployed, it can be
connected to the Temporal operator using the Juju command line as follows:

```bash
juju deploy temporal-admin-k8s
juju relate temporal-k8s:admin temporal-admin-k8s:admin

# Create default namespace:
juju run temporal-admin-k8s/0 tctl args="--ns default namespace register -rd 3"
```

### Deploying Nginx Ingress Integrator

The Temporal operator exposes its ports using the
[Nginx Ingress Integrator](https://charmhub.io/nginx-ingress-integrator)
operator. You must first make sure to have an
[Nginx Ingress Controller](https://docs.nginx.com/nginx-ingress-controller/)
deployed. To enable TLS connections, you must have a TLS certificate stored as a
k8s secret (default name is "temporal-tls"). A self-signed certificate for
development purposes can be created as follows:

```bash
# Generate private key
openssl genrsa -out server.key 2048

# Generate a certificate signing request
openssl req -new -key server.key -out server.csr -subj "/CN=temporal-k8s"

# Create self-signed certificate
openssl x509 -req -days 365 -in server.csr -signkey server.key -out server.crt -extfile <(printf "subjectAltName=DNS:temporal-k8s")

# Create a k8s secret
kubectl create secret tls temporal-tls --cert=server.crt --key=server.key
```

This operator can then be deployed and connected to the Temporal operator using
the Juju command line as follows:

```bash
# Deploy ingress controller.
microk8s enable ingress:default-ssl-certificate=temporal/temporal-tls

juju deploy nginx-ingress-integrator
juju relate temporal-k8s nginx-ingress-integrator
```

Once deployed, the hostname will default to the name of the application
(`temporal-k8s`), and can be configured using the `external-hostname`
configuration on the Temporal operator.

### Deploying Temporal UI

To view workflow runs on a web UI, the Temporal operator requires integration
with the
[Temporal UI operator](https://github.com/canonical/temporal-ui-k8s-operator).
Once the Temporal UI operator is deployed, it can be connected to the Temporal
operator using the Juju command line as follows:

```bash
juju deploy temporal-ui-k8s
juju relate temporal-k8s:ui temporal-ui-k8s:ui
juju relate temporal-ui-k8s nginx-ingress-integrator
```

Once deployed, the hostname will default to the name of the application
(`temporal-ui-k8s`), and can be configured using the `external-hostname`
configuration on the Temporal operator.

### Observability

The Temporal server charm can be related to the
[Canonical Observability Stack](https://charmhub.io/topics/canonical-observability-stack)
in order to collect logs and telemetry. To deploy cos-lite and expose its
endpoints as offers, follow these steps:

```bash
# Deploy the cos-lite bundle:
juju add-model cos
juju deploy cos-lite --trust
```

```bash
# Expose the cos integration endpoints:
juju offer prometheus:metrics-endpoint
juju offer loki:logging
juju offer grafana:grafana-dashboard

# Relate Temporal to the cos-lite apps:
juju switch <TEMPORAL_JUJU_MODEL>
juju relate temporal-k8s admin/cos.grafana
juju relate temporal-k8s admin/cos.loki
juju relate temporal-k8s admin/cos.prometheus
```

After relating the Temporal server charm to cos-lite services, we need, for the
time being, to attach the promtail-bin resource so that Loki works without
trying to download promtail from the web:

```bash
# Download promtail binary
curl -O -L "https://github.com/grafana/loki/releases/download/v2.7.5/promtail-linux-amd64.zip"

# Extract the binary
unzip "promtail-linux-amd64.zip"

# Make sure it is executable
chmod a+x "promtail-linux-amd64"
juju switch <TEMPORAL_JUJU_MODEL>
juju attach-resource temporal-k8s promtail-bin=<PATH_TO_PROMTAIL_BINARY>/promtail-linux-amd64
```

```bash
# Access grafana with username "admin" and password:
juju run grafana/0 -m cos get-admin-password --wait 1m
# Grafana is listening on port 3000 of the app ip address.
# Dashboard can be accessed under "Temporal Server Metrics", make sure to select the juju model which contains your Temporal charm.
```

## Verifying

To verify that the setup is running correctly, run
`juju status --relations --watch 1s` and ensure that all pods are active and all
required integrations exist.

To run a basic workflow, you may use a simple client (e.g.
[sdk-python sample](https://github.com/temporalio/sdk-python#quick-start)) and
connect to the hostname specified in the previous steps (by default, your client
should connect to `temporal-k8s`). As we are using TLS, you must provide the
certificate generated in previous steps as part of your
[TLSConfig](https://python.temporal.io/temporalio.service.TLSConfig.html) when
making requests to the Temporal server.

## Contributing

This charm is still in active development. Please see the
[Juju SDK docs](https://juju.is/docs/sdk) for guidelines on enhancements to this
charm following best practice guidelines, and
[CONTRIBUTING.md](./CONTRIBUTING.md) for developer guidance.
