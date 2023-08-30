# Deploy Temporal Web UI

This is part of the [Charmed Temporal Tutorial](./00-introduction.md). Please
refer to this page for more information and the overview of the content.

The Temporal Web UI is a user interface used to interact with and monitor
Temporal workflows and activities.

## Deploy

To deploy Charmed Temporal Web UI, you need to run the following command, which
will fetch the charm from [Charmhub](https://charmhub.io/temporal-ui-k8s) and
deploy it to your model:

```bash
juju deploy temporal-ui-k8s
```

Wait until the application is ready - when it is ready, `juju status` will show:

```
Model           Controller           Cloud/Region        Version  SLA          Timestamp
temporal-model  temporal-controller  microk8s/localhost  3.1.5    unsupported  16:35:14+03:00

App                 Version  Status   Scale  Charm               Channel    Rev  Address         Exposed  Message
postgresql-k8s      14.7     active       1  postgresql-k8s      14/stable   73  10.152.183.250  no       Primary
temporal-admin-k8s           active       1  temporal-admin-k8s  stable       4  10.152.183.21   no
temporal-k8s                 active       1  temporal-k8s        stable       9  10.152.183.191  no
temporal-ui-k8s              waiting      1  temporal-ui-k8s     stable       8  10.152.183.135  no       installing agent

Unit                   Workload  Agent  Address      Ports   Message
postgresql-k8s/0*      active    idle   10.1.232.66          Primary
temporal-admin-k8s/0*  active    idle   10.1.232.71
temporal-k8s/0*        active    idle   10.1.232.64
temporal-ui-k8s/0*     blocked   idle   10.1.232.72          ui:temporal relation: not available

```

## Relate Temporal Server to Temporal Web UI

To relate the two charms together, run the following command:

```bash
juju relate temporal-k8s:ui temporal-ui-k8s:ui
```

Wait until the two charms have been related and settled - when ready,
`juju status` will show:

```
Model           Controller           Cloud/Region        Version  SLA          Timestamp
temporal-model  temporal-controller  microk8s/localhost  3.1.5    unsupported  16:36:27+03:00

App                 Version  Status  Scale  Charm               Channel    Rev  Address         Exposed  Message
postgresql-k8s      14.7     active      1  postgresql-k8s      14/stable   73  10.152.183.250  no       Primary
temporal-admin-k8s           active      1  temporal-admin-k8s  stable       4  10.152.183.21   no
temporal-k8s                 active      1  temporal-k8s        stable       9  10.152.183.191  no
temporal-ui-k8s              active      1  temporal-ui-k8s     stable       8  10.152.183.135  no

Unit                   Workload  Agent  Address      Ports   Message
postgresql-k8s/0*      active    idle   10.1.232.66          Primary
temporal-admin-k8s/0*  active    idle   10.1.232.71
temporal-k8s/0*        active    idle   10.1.232.64
temporal-ui-k8s/0*     active    idle   10.1.232.72
```

At this point, you can access the web UI using the unit IP address
`10.1.232.72:8080`. Note that the unit IP address might differ in your
deployment. You will be able to see the default namespace and the label "No
Workflows Found" as seen below.

![Temporal Web UI](../media/temporal-web-ui.png)

> **See next: [Deploy Temporal Web UI](./07-deploying-ingress.md)**
