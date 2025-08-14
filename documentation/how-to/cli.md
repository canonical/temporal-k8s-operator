# Temporal CLI

[temporal cli](https://docs.temporal.io/cli) is a command-line tool that can be used
to interact with a Temporal Cluster.

The tool is available for use as follows:

## Temporal client Snap

Temporal cli can be installed as a
[snap](https://snapcraft.io/temporal)
and used on your local machine. The temporal cli snap can be used on Temporal server
environments with authorization enabled by enabling Google IAM login. More
instructions can be found on the snap's documentation page.

## Temporal Admin Charm

Temporal cli commands can be run as an action in the Charmed Temporal Admin K8s
operator. Once deployed and related to the Temporal server, we can run any of
the available commands such as:

### Create Namespace

```bash
juju run temporal-admin-k8s/0 cli args="operator namespace create --namespace default --retention 3d" --wait 1m
```

### List Namespaces

```bash
juju run temporal-admin-k8s/0 cli args="operator namespace list" --wait 1m
```

### Start Workflow Execution

```bash
juju run temporal-admin-k8s/0 cli args='workflow start --task-queue test-queue --type GreetingWorkflow --input '\"World\"'' --wait 1m
```
