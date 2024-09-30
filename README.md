[![Charmhub Badge](https://charmhub.io/temporal-k8s/badge.svg)](https://charmhub.io/temporal-k8s)
[![Release Edge](https://github.com/canonical/temporal-k8s-operator/actions/workflows/test_and_publish_charm.yaml/badge.svg)](https://github.com/canonical/temporal-k8s-operator/actions/workflows/publish_charm.yaml)

# Temporal K8s Operator

This is the Kubernetes Python Operator for [Temporal](https://temporal.io/).

## Description

Temporal is a developer-first, open source platform that ensures the successful
execution of services and applications (using workflows).

Use Workflow as Code (TM) to build and operate resilient applications. Leverage
developer friendly primitives and avoid fighting your infrastructure

This [operator](https://charmhub.io/temporal-k8s) provides a Temporal server,
and consists of Python scripts which wraps the versions distributed by
[temporalio](https://hub.docker.com/r/temporalio/server).

## Usage

Note: This operator requires the use of juju>=3.1.

The following documents provide a good starting point for using this charm:

- [Tutorial](./documentation/tutorial/01-introduction.md)
- [How-To](./documentation/how-to/)
- [Explanation](./documentation/explanation/)
- [Reference](https://charmhub.io/temporal-k8s/configure)

## Contributing

This charm is still in active development. Please see the
[Juju SDK docs](https://juju.is/docs/sdk) for guidelines on enhancements to this
charm following best practice guidelines, and
[CONTRIBUTING.md](./CONTRIBUTING.md) for developer guidance.
