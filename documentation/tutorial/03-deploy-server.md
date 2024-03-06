# Deploy Temporal Server

This is part of the
[Charmed Temporal Tutorial](https://discourse.charmhub.io/t/charmed-temporal-k8s-tutorial-introduction/11777).
Please refer to this page for more information and the overview of the content.

The [Temporal server](https://docs.temporal.io/clusters#temporal-server) is a
group of four independently scalable services (frontend, history, matching and
worker). It is responsible for state management and task synchronization among
other functionalities.

## Deploy

To deploy Charmed Temporal K8s, all you need to do is run the following command,
which will fetch the charm from [Charmhub](https://charmhub.io/temporal-k8s) and
deploy it to your model:

```bash
juju deploy temporal-k8s --config num-history-shards=4
```

Juju will now fetch Charmed Temporal K8s and begin deploying it to the local
MicroK8s. This process can take several minutes depending on how provisioned
(RAM, CPU, etc) your machine is. You can track the progress by running:

```bash
juju status --watch 1s

# Output:
Located charm "temporal-k8s" in charm-hub, revision 9
Deploying "temporal-k8s" from charm-hub charm "temporal-k8s", revision 9 in channel stable on ubuntu@22.04/stable
```

This command is useful for checking the status of Charmed Temporal K8s and
gathering information about the machines hosting Charmed Temporal K8s. Some of
the helpful information it displays include IP addresses, ports, state, etc. The
command updates the status of Charmed Temporal K8s every second and as the
application starts you can watch the status and messages of Charmed Temporal K8s
change. Wait until the application is ready - when it is ready, `juju status`
will show:

```
Model           Controller           Cloud/Region        Version  SLA          Timestamp
temporal-model  temporal-controller  microk8s/localhost  3.1.5    unsupported  11:27:49+03:00

App             Version  Status   Scale  Charm         Channel  Rev  Address         Exposed  Message
temporal-k8s             waiting      1  temporal-k8s  stable     9  10.152.183.191  no       installing agent

Unit             Workload  Agent  Address      Ports  Message
temporal-k8s/0*  blocked   idle   10.1.232.64         database relation not ready
```

To exit the screen with `juju status --watch 1s`, enter `Ctrl+c`. If you want to
further inspect juju logs, can watch for logs with `juju debug-log`. More info
on logging at [juju logs](https://juju.is/docs/olm/juju-logs).

Note: When deploying Charmed Temporal K8s previously, we set the
`num-history-shards` configuration parameter to 4. More information can be found
about history shards in the official Temporalio documentation. For development
environments, a value of 4 should be more than sufficient.

> **See next:
> [Deploy PostgreSQL Database](https://discourse.charmhub.io/t/charmed-temporal-k8s-tutorial-deploy-postgresql-database/11780)**
