The Charmed Temporal K8s Operator delivers automated operations management from
day 0 to day 2 on [Temporal](https://temporal.io/). It is an open source,
end-to-end, production-ready workflow engine on top of [Juju](https://juju.is/).

Temporal is a developer-first, open source platform that ensures the successful
execution of services and applications (using workflows). Use Workflow as Code
(TM) to build and operate resilient applications. Leverage developer friendly
primitives and avoid fighting your infrastructure

This operator provides a Temporal server, and consists of Python scripts which
wraps the versions distributed by
[temporalio](https://hub.docker.com/r/temporalio/server).

The Charmed Temporal K8s operator offers features such as replication,
observability and easy to use integration with applications. It addresses the
requirement for deploying Temporal in a structured and uniform fashion, while
allowing the user flexibility in configuration. It streamlines the process of
deploying, scaling, configuring and overseeing Temporal at scale in a dependable
manner for production purposes.

## Project and community

Temporal Server Charm is a member of the Ubuntu family. It’s an open source
project that warmly welcomes community projects, contributions, suggestions,
fixes and constructive feedback.

- [Read our Code of Conduct](https://ubuntu.com/community/code-of-conduct)
- [Join the Discourse forum](https://discourse.charmhub.io/tag/temporal)
- [Contribute and report bugs](https://github.com/canonical/temporal-k8s-operator)

## In this documentation

|                                                                                                                                                  |                                                                                               |
| ------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------- |
| [Tutorial](./tutorial/00-introduction.md) </br> Get started - a hands-on introduction to using Charmed Temporal K8s operator for new users </br> | [How-to guides](./how-to/) </br> Step-by-step guides covering key operations and common tasks |
| [Reference](https://charmhub.io/temporal-k8s/actions) </br> Technical information - specifications, APIs, architecture                           | [Explanation](./explanation/) </br> Concepts - discussion and clarification of key topics     |

# Navigation

| Level | Path                | Navlink                                                               |
| ----- | ------------------- | --------------------------------------------------------------------- |
| 1     | tutorial            | [Tutorial]()                                                          |
| 2     | t-overview          | [1. Introduction](./tutorial/01-introduction.md)                      |
| 2     | t-setup-environment | [2. Environment Setup](./tutorial/02-environment.md)                  |
| 2     | t-deploy-server     | [3. Deploy Temporal Server](./tutorial/03-deploy-server.md)           |
| 2     | t-deploy-db         | [4. Deploy PostgreSQL Database](./tutorial/04-deploy-db.md)           |
| 2     | t-deploy-admin      | [5. Deploy Temporal Admin](./tutorial/05-deploy-admin.md)             |
| 2     | t-deploy-ui         | [6. Deploy Temporal Web UI](./tutorial/06-deploy-ui.md)               |
| 2     | t-deploy-ingress    | [7. Deploy Nginx Ingress Integrator](./tutorial/07-deploy-ingress.md) |
| 2     | t-deploy-worker     | [8. Deploy Temporal Worker](./tutorial/08-deploy-worker.md)           |
| 2     | t-run-workflow      | [9. Run Your First Workflow](./tutorial/09-run-workflow.md)           |
| 2     | t-cleanup           | [10. Cleanup and Extra Info](./tutorial/10-cleanup.md)                |
| 1     | how-to              | [How To]()                                                            |
| 2     | h-observability     | [Observability](./how-to/observability.md)                            |
| 2     | h-scaling           | [Scaling](./how-to/scaling.md)                                        |
| 2     | h-tctl              | [TCTL](./how-to/tctl.md)                                              |
| 1     | reference           | [Reference]()                                                         |
| 2     | r-actions           | [Actions](https://charmhub.io/temporal-k8s/actions)                   |
| 2     | r-configurations    | [Configurations](https://charmhub.io/temporal-k8s/configure)          |
| 2     | r-integrations      | [Integrations](https://charmhub.io/temporal-k8s/integrations)         |
| 1     | explanation         | [Explanation]()                                                       |
| 2     | e-architecture      | [Architecture](./explanation/architecture.md)                         |

# Redirects

[details=Mapping table] | Path | Location | | ---- | -------- | [/details]
