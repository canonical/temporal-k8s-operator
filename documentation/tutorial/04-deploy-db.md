# Deploy PostgreSQL Database

This is part of the [Charmed Temporal Tutorial](./01-introduction.md). Please
refer to this page for more information and the overview of the content.

For Temporal [persistence](https://docs.temporal.io/clusters#persistence) and
[visibility](https://docs.temporal.io/clusters#visibility), we use the
[PostgreSQL K8s](https://charmhub.io/postgresql-k8s) charmed operator. The
PostgreSQL K8s charm can be deployed and related to the Temporal server.

## Deploy

To deploy Charmed PostgreSQL K8s, you need to run the following command, which
will fetch the charm from [Charmhub](https://charmhub.io/postgresql-k8s) and
deploy it to your model:

```bash
juju deploy postgresql-k8s --channel 14/stable --trust
```

Wait until the application is ready - when it is ready, `juju status` will show:

```
Model           Controller           Cloud/Region        Version  SLA          Timestamp
temporal-model  temporal-controller  microk8s/localhost  3.1.5    unsupported  12:32:16+03:00

App             Version  Status   Scale  Charm           Channel    Rev  Address         Exposed  Message
postgresql-k8s  14.7     active       1  postgresql-k8s  14/stable   73  10.152.183.250  no
temporal-k8s             waiting      1  temporal-k8s    stable       9  10.152.183.191  no       installing agent

Unit               Workload  Agent  Address      Ports  Message
postgresql-k8s/0*  active    idle   10.1.232.66
temporal-k8s/0*    blocked   idle   10.1.232.64         database relation not ready
```

## Relate Temporal Server to PostgresQL K8s

To relate the two charms together, run the following command:

```bash
juju relate temporal-k8s:db postgresql-k8s:database
juju relate temporal-k8s:visibility postgresql-k8s:database
```

Wait until the two charms have been related and settled - when ready,
`juju status --relations` will show:

```
Model           Controller           Cloud/Region        Version  SLA          Timestamp
temporal-model  temporal-controller  microk8s/localhost  3.1.5    unsupported  12:35:24+03:00

App             Version  Status   Scale  Charm           Channel    Rev  Address         Exposed  Message
postgresql-k8s  14.7     active       1  postgresql-k8s  14/stable   73  10.152.183.250  no       Primary
temporal-k8s             waiting      1  temporal-k8s    stable       9  10.152.183.191  no       installing agent

Unit               Workload  Agent  Address      Ports  Message
postgresql-k8s/0*  active    idle   10.1.232.66         Primary
temporal-k8s/0*    blocked   idle   10.1.232.64         admin:temporal relation: schema is not ready

Relation provider                 Requirer                       Interface          Type     Message
postgresql-k8s:database           temporal-k8s:db                postgresql_client  regular
postgresql-k8s:database           temporal-k8s:visibility        postgresql_client  regular
postgresql-k8s:database-peers     postgresql-k8s:database-peers  postgresql_peers   peer
postgresql-k8s:restart            postgresql-k8s:restart         rolling_op         peer
temporal-k8s:peer                 temporal-k8s:peer              temporal           peer
```

> **See next: [Deploy Temporal Admin](./04-deploying-admin.md)**
