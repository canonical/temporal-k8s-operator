# Deploy Temporal Server

This is part of the
[Charmed Temporal Tutorial](https://discourse.charmhub.io/t/charmed-temporal-k8s-tutorial-introduction/11777).
Please refer to this page for more information and the overview of the content.

The [Temporal server](https://docs.temporal.io/clusters#temporal-server) is a
group of four independently scalable services (frontend, history, matching and
worker). It is responsible for state management and task synchronization among
other functionalities.

## Requirements

- You have completed [Environment Setup](./02-environment.md).

## Deploy

To deploy Charmed Temporal K8s, all you need to do is run the following command,
which will fetch the charm from [Charmhub](https://charmhub.io/temporal-k8s) and
deploy it to your model:

```bash
juju deploy temporal-k8s --channel 1.31/stable --base ubuntu@26.04 --config num-history-shards=4
```

[note]
**About `num-history-shards`.** The value must be a **power of two** (1, 2, 4, 8, 16, …) and is **deployment-time-only**, it cannot be changed after the charm is deployed without a fresh deployment and data migration. `4` is a reasonable default for development; production deployments typically pick a higher power of two based on expected workflow throughput.

For more information about history shards, see the [official Temporal documentation](https://docs.temporal.io/temporal-service/temporal-server#history-shard).
[/note]

## Check status

Monitor the model while the application starts up:
```bash
juju status --watch 1s
```
Wait until the application stabilizes. At this point, it should be blocked, waiting for a database with the message `database relation not ready`

> **See next:
> [Deploy PostgreSQL Database](https://discourse.charmhub.io/t/charmed-temporal-k8s-tutorial-deploy-postgresql-database/11780)**



