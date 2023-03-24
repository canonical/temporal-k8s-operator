[![Charmhub Badge](https://charmhub.io/temporal-k8s/badge.svg)](https://charmhub.io/temporal-k8s)
[![Release Edge](https://github.com/canonical/temporal-k8s-operator/actions/workflows/test_and_publish_charm.yaml)](https://github.com/canonical/temporal-k8s-operator/actions/workflows/test_and_publish_charm.yaml)

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
juju deploy postgresql-k8s --channel edge --trust
juju relate temporal-k8s:db postgresql-k8s:db
juju relate temporal-k8s:visibility postgresql-k8s:db
```

### Deploying Temporal Admin
On initial deployment, the Temporal operator requires integration with the [Temporal Admin operator](https://github.com/canonical/temporal-admin-k8s-operator) for schema creation. Once the Temporal Admin operator is deployed, it can be connected to the Temporal operator using the Juju command line as follows:

```bash
juju deploy temporal-admin-k8s
juju relate temporal-k8s:admin temporal-admin-k8s:admin
```

### Deploying Nginx Ingress Integrator
The Temporal operator exposes itself using the [Nginx Ingress Integrator](https://charmhub.io/nginx-ingress-integrator) operator. You must first make sure to have an [Nginx Ingress Controller](https://docs.nginx.com/nginx-ingress-controller/) deployed. This operator can then be deployed and connected to the Temporal operator using the Juju command line as follows:

```bash
# Deploy ingress controller.
microk8s enable ingress

juju deploy nginx-ingress-integrator
juju relate temporal-k8s:ingress nginx-ingress-integrator:ingress
```

Once deployed, the hostname will default to the name of the application (```temporal-k8s```), and can be configured using the ```external-hostname``` configuration on the Temporal operator.

Note: The Temporal operator currently does not support TLS functionality. As such, please check [CONTRIBUTING.md](./CONTRIBUTING.md) for instructions on how to enable insecure HTTP/2 connections on port 80 as a temporary workaround.

### Deploying Temporal UI
To view workflow runs on a web UI, the Temporal operator requires integration with the [Temporal UI operator](https://github.com/canonical/temporal-ui-k8s-operator). Once the Temporal UI operator is deployed, it can be connected to the Temporal operator using the Juju command line as follows:

```bash
juju deploy temporal-ui-k8s
juju relate temporal-k8s:ui temporal-ui-k8s:ui
```

Once deployed, the hostname will default to the name of the application (```temporal-ui-k8s```), and can be configured using the ```external-hostname``` configuration on the Temporal operator.

Note: As mentioned previously, the Temporal operator currently does not support TLS functionality. As such, please check [CONTRIBUTING.md](./CONTRIBUTING.md) for instructions on how to access the web UI as a temporary workaround.

## Verifying
To verify that the setup is running correctly, run ```juju status --relations --watch 1s``` and ensure that all pods are active and all required integrations exist.

To run a basic workflow, you may use a simple client (e.g. [sdk-python sample](https://github.com/temporalio/sdk-python#quick-start)) and connect to the hostname specified in the previous steps (by default, your client should connect to ```temporal-k8s:80```).

## Contributing

This charm is still in active development. Please see the
[Juju SDK docs](https://juju.is/docs/sdk) for guidelines on enhancements to this charm
following best practice guidelines, and [CONTRIBUTING.md](./CONTRIBUTING.md) for developer guidance.
