The Charmed Temporal K8s Operator delivers automated operations management from
day 0 to day 2 on [Temporal](https://temporal.io/). It is an open source,
end-to-end, production-ready workflow engine on top of [Juju](https://juju.is/).

Temporal is a developer-first, open source platform that ensures the successful
execution of services and applications (using workflows). Use Workflow as Code
(TM) to build and operate resilient applications. Leverage developer friendly
primitives and avoid fighting your infrastructure.

This operator provides a Temporal server, and consists of Python scripts which
wraps the versions distributed by
[temporalio](https://hub.docker.com/r/temporalio/server).

The Charmed Temporal K8s operator offers features such as replication,
observability and easy to use integration with applications. It addresses the
requirement for deploying Temporal in a structured and uniform fashion, while
allowing the user flexibility in configuration. It streamlines the process of
deploying, scaling, configuring and overseeing Temporal at scale in a dependable
manner for production purposes.

## In This Documentation

|                                                                                                                                                                        |                                                                                                                                        |
| ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| [Tutorial](/t/charmed-temporal-k8s-tutorial-introduction/11777) </br> Get started - a hands-on introduction to using Charmed Temporal K8s operator for new users </br> | [How-to guides](/t/charmed-temporal-k8s-how-to-observability/11787) </br> Step-by-step guides covering key operations and common tasks |
| [Reference](https://charmhub.io/temporal-k8s/actions) </br> Technical information - specifications, APIs, architecture                                                 | [Explanation](/t/charmed-temporal-k8s-explanations-architecture/11789) </br> Concepts - discussion and clarification of key topics     |

# Navigation

| Level | Path                | Navlink                                                                                                      |
| ----- | ------------------- | ------------------------------------------------------------------------------------------------------------ |
| 1     | tutorial            | [Tutorial]()                                                                                                 |
| 2     | t-introduction      | [1. Introduction](/t/charmed-temporal-k8s-tutorial-introduction/11777)                                       |
| 2     | t-setup-environment | [2. Environment Setup](/t/charmed-temporal-k8s-tutorial-environment-setup/11778)                             |
| 2     | t-deploy-server     | [3. Deploy Temporal Server](/t/charmed-temporal-k8s-tutorial-deploy-temporal-server/11779)                   |
| 2     | t-deploy-db         | [4. Deploy PostgreSQL Database](/t/charmed-temporal-k8s-tutorial-deploy-postgresql-database/11780)           |
| 2     | t-deploy-admin      | [5. Deploy Temporal Admin](/t/charmed-temporal-k8s-tutorial-deploy-temporal-admin/11781)                     |
| 2     | t-deploy-ui         | [6. Deploy Temporal Web UI](/t/charmed-temporal-k8s-tutorial-deploy-temporal-web-ui/11782)                   |
| 2     | t-deploy-ingress    | [7. Deploy Nginx Ingress Integrator](/t/charmed-temporal-k8s-tutorial-deploy-nginx-ingress-integrator/11783) |
| 2     | t-deploy-worker     | [8. Deploy Temporal Worker](/t/charmed-temporal-k8s-tutorial-deploy-temporal-worker/11784)                   |
| 2     | t-run-workflow      | [9. Run Your First Workflow](/t/charmed-temporal-k8s-tutorial-run-your-first-workflow/11785)                 |
| 2     | t-cleanup           | [10. Cleanup and Extra Info](/t/charmed-temporal-k8s-tutorial-cleanup-and-extra-info/11786)                  |
| 1     | how-to              | [How to]()                                                                                                   |
| 2     | h-authentication    | [Authentication](TODO)                                                                                       |
| 2     | h-authorization     | [Authorization](TODO)                                                                                        |
| 2     | h-observability     | [Observability](/t/charmed-temporal-k8s-how-to-observability/11787)                                          |
| 2     | how-to-scaling      | [Scaling](/t/10840)                                                                                          |
| 2     | h-tctl              | [TCTL](/t/charmed-temporal-k8s-how-to-tctl/11788)                                                            |
| 1     | reference           | [Reference]()                                                                                                |
| 2     | r-actions           | [Actions](https://charmhub.io/temporal-k8s/actions)                                                          |
| 2     | r-configurations    | [Configurations](https://charmhub.io/temporal-k8s/configure)                                                 |
| 2     | r-integrations      | [Integrations](https://charmhub.io/temporal-k8s/integrations)                                                |
| 1     | e-architecture      | [Architecture](/t/charmed-temporal-k8s-explanations-architecture/11789)                                      |

# Redirects

[details=Mapping table] | Path | Location | | ---- | -------- | [/details]

## Project and Community

Charmed Temporal K8s is a member of the Ubuntu family. It’s an open source
project that warmly welcomes community projects, contributions, suggestions,
fixes and constructive feedback.

- [Read our Code of Conduct](https://ubuntu.com/community/code-of-conduct)
- [Join the Discourse forum](https://discourse.charmhub.io/tag/temporal)
- [Contribute and report bugs](https://github.com/canonical/temporal-k8s-operator)
