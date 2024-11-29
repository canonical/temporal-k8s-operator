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

|                                                                                                                                                                                                     |                                                                                                                                                                     |
| --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [Tutorial](https://discourse.charmhub.io/t/charmed-temporal-k8s-tutorial-introduction/11777) </br> Get started - a hands-on introduction to using Charmed Temporal K8s operator for new users </br> | [How-to guides](https://discourse.charmhub.io/t/charmed-temporal-k8s-how-to-observability/11787) </br> Step-by-step guides covering key operations and common tasks |
| [Reference](https://charmhub.io/temporal-k8s/actions) </br> Technical information - specifications, APIs, architecture                                                                              | [Explanation](https://discourse.charmhub.io/t/charmed-temporal-k8s-explanations-architecture/11789) </br> Concepts - discussion and clarification of key topics     |

# Navigation

| Level | Path                | Navlink                                                                                                                                   |
| ----- | ------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| 1     | tutorial            | [Tutorial](https://discourse.charmhub.io/t/charmed-temporal-k8s-tutorial-introduction/11777)                                              |
| 2     | t-introduction      | [1. Introduction](https://discourse.charmhub.io/t/charmed-temporal-k8s-tutorial-introduction/11777)                                       |
| 2     | t-setup-environment | [2. Environment Setup](https://discourse.charmhub.io/t/charmed-temporal-k8s-tutorial-environment-setup/11778)                             |
| 2     | t-deploy-server     | [3. Deploy Temporal Server](https://discourse.charmhub.io/t/charmed-temporal-k8s-tutorial-deploy-temporal-server/11779)                   |
| 2     | t-deploy-db         | [4. Deploy PostgreSQL Database](https://discourse.charmhub.io/t/charmed-temporal-k8s-tutorial-deploy-postgresql-database/11780)           |
| 2     | t-deploy-admin      | [5. Deploy Temporal Admin](https://discourse.charmhub.io/t/charmed-temporal-k8s-tutorial-deploy-temporal-admin/11781)                     |
| 2     | t-deploy-ui         | [6. Deploy Temporal Web UI](https://discourse.charmhub.io/t/charmed-temporal-k8s-tutorial-deploy-temporal-web-ui/11782)                   |
| 2     | t-deploy-ingress    | [7. Deploy Nginx Ingress Integrator](https://discourse.charmhub.io/t/charmed-temporal-k8s-tutorial-deploy-nginx-ingress-integrator/11783) |
| 2     | t-deploy-worker     | [8. Deploy Temporal Worker](https://discourse.charmhub.io/t/charmed-temporal-k8s-tutorial-deploy-temporal-worker/11784)                   |
| 2     | t-run-workflow      | [9. Run Your First Workflow](https://discourse.charmhub.io/t/charmed-temporal-k8s-tutorial-run-your-first-workflow/11785)                 |
| 2     | t-cleanup           | [10. Cleanup and Extra Info](https://discourse.charmhub.io/t/charmed-temporal-k8s-tutorial-cleanup-and-extra-info/11786)                  |
| 1     | how-to              | [How to](https://discourse.charmhub.io/t/charmed-temporal-k8s-how-to-index/13740)                                                         |
| 2     | h-authentication    | [Authentication](https://discourse.charmhub.io/t/charmed-temporal-k8s-how-to-authentication/12586)                                        |
| 2     | h-authorization     | [Authorization](https://discourse.charmhub.io/t/charmed-temporal-k8s-how-to-authorization/12587)                                          |
| 2     | h-observability     | [Observability](https://discourse.charmhub.io/t/charmed-temporal-k8s-how-to-observability/11787)                                          |
| 2     | h-scaling           | [Scaling](https://discourse.charmhub.io/t/10840)                                                                                          |
| 2     | h-tctl              | [TCTL](https://discourse.charmhub.io/t/charmed-temporal-k8s-how-to-tctl/11788)                                                            |
| 2     | h-server-upgrades   | [Server Upgrades](https://discourse.charmhub.io/t/charmed-temporal-k8s-how-to-server-upgrades/13105)                                      |
| 2     | h-archival          | [Enable Archival](https://discourse.charmhub.io/t/charmed-temporal-k8s-how-to-enable-archival/13106)                                      |
| 1     | reference           | [Reference](https://discourse.charmhub.io/t/charmed-temporal-k8s-reference-index/13741)                                                   |
| 2     | r-actions           | [Actions](https://charmhub.io/temporal-k8s/actions)                                                                                       |
| 2     | r-configurations    | [Configurations](https://charmhub.io/temporal-k8s/configure)                                                                              |
| 2     | r-integrations      | [Integrations](https://charmhub.io/temporal-k8s/integrations)                                                                             |
| 2     | r-security          | [Security](https://discourse.charmhub.io/t/charmed-temporal-k8s-reference-security/16052)                                                 |
| 1     | e-architecture      | [Architecture](https://discourse.charmhub.io/t/charmed-temporal-k8s-explanations-architecture/11789)                                      |

# Redirects

[details=Mapping table] | Path | Location | | ---- | -------- | [/details]

## Project and Community

Charmed Temporal K8s is a member of the Ubuntu family. It’s an open source
project that warmly welcomes community projects, contributions, suggestions,
fixes and constructive feedback.

- [Read our Code of Conduct](https://ubuntu.com/community/code-of-conduct)
- [Join the Discourse forum](https://discourse.charmhub.io/tag/temporal)
- [Contribute and report bugs](https://github.com/canonical/temporal-k8s-operator)
