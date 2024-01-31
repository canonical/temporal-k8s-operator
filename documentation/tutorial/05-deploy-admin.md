# Deploy Temporal Admin

This is part of the
[Charmed Temporal Tutorial](https://discourse.charmhub.io/t/charmed-temporal-k8s-tutorial-introduction/11777).
Please refer to this page for more information and the overview of the content.

The Temporal Admin Tools are a set of command-line utilities used to configure
and support the Temporal server.

## Deploy

To deploy Charmed Temporal Admin, you need to run the following command, which
will fetch the charm from [Charmhub](https://charmhub.io/temporal-admin-k8s) and
deploy it to your model:

```bash
juju deploy temporal-admin-k8s
```

Wait until the application is ready - when it is ready, `juju status` will show:

```
Model           Controller           Cloud/Region        Version  SLA          Timestamp
temporal-model  temporal-controller  microk8s/localhost  3.1.5    unsupported  12:32:16+03:00

App                 Version   Status   Scale  Charm                Channel    Rev  Address         Exposed  Message
postgresql-k8s      14.7      active       1  postgresql-k8s       14/stable   73  10.152.183.250  no       Primary
temporal-admin-k8s            waiting      1  temporal-admin-k8s   stable       4  10.152.183.21   no       installing agent
temporal-k8s                  waiting      1  temporal-k8s         stable       9  10.152.183.191  no       installing agent

Unit                   Workload  Agent  Address      Ports  Message
postgresql-k8s/0*      active    idle   10.1.232.66
temporal-admin-k8s/0*  blocked   idle   10.1.232.71         admin:temporal relation: database connections info not available
temporal-k8s/0*        blocked   idle   10.1.232.64          admin:temporal relation: schema is not ready
```

## Relate Temporal Server to Temporal Admin

To relate the two charms together, run the following command:

```bash
juju relate temporal-k8s:admin temporal-admin-k8s:admin
```

Wait until the two charms have been related and settled - when ready,
`juju status --relations` will show:

```
Model           Controller           Cloud/Region        Version  SLA          Timestamp
temporal-model  temporal-controller  microk8s/localhost  3.1.5    unsupported  12:35:24+03:00

App                 Version   Status   Scale  Charm                Channel    Rev  Address         Exposed  Message
postgresql-k8s      14.7      active      1   postgresql-k8s       14/stable   73  10.152.183.250  no       Primary
temporal-admin-k8s            active      1   temporal-admin-k8s   stable       4  10.152.183.21   no
temporal-k8s                  active      1   temporal-k8s         stable       9  10.152.183.191  no

Unit                   Workload  Agent  Address      Ports  Message
postgresql-k8s/0*      active    idle   10.1.232.66         Primary
temporal-admin-k8s/0*  active    idle   10.1.232.71
temporal-k8s/0*        active    idle   10.1.232.64

Relation provider                 Requirer                       Interface          Type     Message
postgresql-k8s:database           temporal-k8s:db                postgresql_client  regular
postgresql-k8s:database           temporal-k8s:visibility        postgresql_client  regular
postgresql-k8s:database-peers     postgresql-k8s:database-peers  postgresql_peers   peer
postgresql-k8s:restart            postgresql-k8s:restart         rolling_op         peer
temporal-admin-k8s:admin          temporal-k8s:admin             temporal           regular
temporal-k8s:peer                 temporal-k8s:peer              temporal           peer
```

You can run the following command to create the initial Temporal namespace:

```bash
# Create default namespace:
juju run temporal-admin-k8s/0 tctl args="--ns default namespace register -rd 3"

# Output:
Running operation 19 with 1 task
  - task 20 on unit-temporal-admin-k8s-0

Waiting for task 20...
output: |
  creating config dir: /root/.config/temporalio
  creating config file: /root/.config/temporalio/tctl.yaml
  Namespace default successfully registered.
result: command succeeded
```

> **See next:
> [Deploy Temporal Web UI](https://discourse.charmhub.io/t/charmed-temporal-k8s-tutorial-deploy-temporal-web-ui/11782)**
