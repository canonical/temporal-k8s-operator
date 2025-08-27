# Deploy PostgreSQL Database

This is part of the
[Charmed Temporal Tutorial](https://discourse.charmhub.io/t/charmed-temporal-k8s-tutorial-introduction/11777).
Please refer to this page for more information and the overview of the content.

For Temporal [persistence](https://docs.temporal.io/clusters#persistence) and
[visibility](https://docs.temporal.io/clusters#visibility), we use the
[PostgreSQL K8s](https://charmhub.io/postgresql-k8s) charmed operator. The
PostgreSQL K8s charm can be deployed and related to the Temporal server.

## Requirements

- You have completed [Deploy Temporal Server](./03-deploy-server.md).
- A controller, `temporal-controller`, and a model, `temporal-model`, are available.
- The application `temporal-k8s` is deployed to `temporal-model` and is currently in `blocked` state, awaiting a database relation.

## Deploy PostgreSQL

To deploy Charmed PostgreSQL K8s, you need to run the following command, which
will fetch the charm from [Charmhub](https://charmhub.io/postgresql-k8s) and
deploy it to your model:

```bash
juju deploy postgresql-k8s --channel 14/stable
```
Wait for PostgreSQL to become active:
```
juju status
```
Wait until the application is ready - when it is ready, `juju status` will show:
```

Model           Controller           Cloud/Region  Version  SLA          Timestamp
temporal-model  temporal-controller  ck8s          3.6.9    unsupported  22:32:26Z

App             Version  Status   Scale  Charm           Channel        Rev  Address         Exposed  Message
postgresql-k8s  14.15    active       1  postgresql-k8s  14/stable      495  10.152.183.200  no
temporal-k8s             blocked      1  temporal-k8s    latest/stable   43  10.152.183.120  no       database relation not ready

Unit               Workload  Agent  Address     Ports  Message
postgresql-k8s/0*  active    idle   10.1.0.36          Primary
temporal-k8s/0*    blocked   idle   10.1.0.152         database relation not ready
```
## Create relations

Temporal requires two PostgreSQL connections: `db` and `visibility`.
```
juju relate temporal-k8s:db postgresql-k8s:database
juju relate temporal-k8s:visibility postgresql-k8s:database
```
Check relations:
```
juju status --relations
```
Wait until the application is ready. Once it is ready, it shows the following:

```
Model           Controller           Cloud/Region  Version  SLA          Timestamp
temporal-model  temporal-controller  ck8s          3.6.9    unsupported  22:35:07Z

App             Version  Status   Scale  Charm           Channel        Rev  Address         Exposed  Message
postgresql-k8s  14.15    active       1  postgresql-k8s  14/stable      495  10.152.183.200  no
temporal-k8s             blocked      1  temporal-k8s    latest/stable   43  10.152.183.120  no       admin:temporal relation: schema is not ready

Unit               Workload  Agent  Address     Ports  Message
postgresql-k8s/0*  active    idle   10.1.0.36          Primary
temporal-k8s/0*    blocked   idle   10.1.0.152         admin:temporal relation: schema is not ready

Integration provider           Requirer                       Interface          Type     Message
postgresql-k8s:database        temporal-k8s:db                postgresql_client  regular
postgresql-k8s:database        temporal-k8s:visibility        postgresql_client  regular
postgresql-k8s:database-peers  postgresql-k8s:database-peers  postgresql_peers   peer
postgresql-k8s:restart         postgresql-k8s:restart         rolling_op         peer
postgresql-k8s:upgrade         postgresql-k8s:upgrade         upgrade            peer
temporal-k8s:peer              temporal-k8s:peer              temporal           peer
```

[note]
At this point, the server may still show that the schema is not ready. This is expected.
The schema will be created after deploying and relating Temporal Admin in the next step.
[/note]

> **See next:
> [Deploy Temporal Admin](https://discourse.charmhub.io/t/charmed-temporal-k8s-tutorial-deploy-temporal-admin/11781)**
