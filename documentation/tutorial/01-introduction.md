# Charmed Temporal Tutorial

The Charmed Temporal K8s operator delivers automated operations management from
day 0 to day 2 on [Temporal](https://temporal.io/). It is an open source,
end-to-end, production-ready workflow engine on top of [Juju](https://juju.is/).
This tutorial will cover the following:

- [Environment Setup](./02-environment.md)
- [Deploy Temporal Server](./03-deploy-server.md)
- [Deploy PostgreSQL Database](./04-deploy-db.md)
- [Deploy Temporal Admin](./05-deploy-admin.md)
- [Deploy Temporal Web UI](./06-deploy-ui.md)
- [Deploy Nginx Ingress Integrator](./07-deploy-ingress.md)
- [Deploy Temporal Worker](./08-deploy-worker.md)
- [Run Your First Workflow](./09-run-workflow.md)
- [Cleanup and Extra Info](./10-cleanup.md)

This tutorial assumes a basic understanding of the following:

- Linux commands.
- Temporal concepts such as workflows, activities and workers. To learn more
  about these concepts, visit the
  [Temporal Documentation](https://docs.temporal.io/concepts).

## License

The Charmed Temporal K8s Operator is free software, distributed under the Apache
Software License, version 2.0. See
[License](https://github.com/canonical/temporal-k8s-operator/blob/main/LICENSE)
for more details.
