# Deploy Temporal Server

This is part of the
[Charmed Temporal Tutorial](https://discourse.charmhub.io/t/charmed-temporal-k8s-tutorial-introduction/11777).
Please refer to this page for more information and the overview of the content.

The [Temporal server](https://docs.temporal.io/clusters#temporal-server) is a
group of four independently scalable services (frontend, history, matching and
worker). It is responsible for state management and task synchronization among
other functionalities.

## Prerequisites

- You have completed [Environment Setup](./02-environment.md).
- A controller (`temporal-controller`) and model (`temporal-model`) are available.

## Deploy

To deploy Charmed Temporal K8s, all you need to do is run the following command,
which will fetch the charm from [Charmhub](https://charmhub.io/temporal-k8s) and
deploy it to your model:

```bash
juju deploy temporal-k8s --config num-history-shards=4
```
## Check status

Watch the model while the application is brought up:
```
juju status --watch 1s
```
Wait until the application settles. At this point, it is expected to be blocked, awaiting a database:
```
App           Version  Status   Scale  Charm         Channel        Rev  Address         Exposed  Message
temporal-k8s           blocked      1  temporal-k8s  latest/stable   43  10.152.183.120  no       database relation not ready

Unit             Workload  Agent  Address     Ports  Message
temporal-k8s/0*  blocked   idle   10.1.0.152         database relation not ready
```
Press Ctrl+C to exit the watch.
> **Note**  
> `num-history-shards`=4 is a good default for development. You can adjust later if needed. More information can be found about history shards in the official Temporalio documentation.



See next: Deploy PostgreSQL Database


> **See next:
> [Deploy PostgreSQL Database](https://discourse.charmhub.io/t/charmed-temporal-k8s-tutorial-deploy-postgresql-database/11780)**



