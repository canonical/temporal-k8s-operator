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

The Temporal and PostgreSQL operators can be deployed and connected to each
other using the Juju command line as follows:

```bash
juju deploy temporal-k8s
juju deploy postgresql-k8s --channel edge --trust
juju relate temporal-k8s postgresql-k8s:db
juju relate temporal-k8s:visibility postgresql-k8s:db
```

## Contributing

This charm is still in active development. Please see the
[Juju SDK docs](https://juju.is/docs/sdk) for guidelines on enhancements to this charm
following best practice guidelines, and `CONTRIBUTING.md` for developer guidance.
