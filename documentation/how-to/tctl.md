# Temporal CLI

[tctl](https://docs.temporal.io/tctl-v1) is a command-line tool that can be used
to interact with a Temporal Cluster.

The tool is available for use as follows:

## Tctl Snap

Tctl can be installed as a
[snap](https://github.com/canonical/charmed-temporal-image/tree/main/tctl-snap)
and used on your local machine. The tctl snap can be used on Temporal server
environments with authorization enabled by enabling Google IAM login. More
instructions can be found on the snap's documentation page.

## Temporal Admin Charm

Tctl commands can be run as an action in the Charmed Temporal Admin K8s
operator. Once deployed and related to the Temporal server, we can run any of
the available commands such as:

### Create Namespace

```bash
juju run temporal-admin-k8s/0 tctl args="--ns default namespace register -rd 3" --wait 1m
```

### List Namespaces

```bash
juju run temporal-admin-k8s/0 tctl args="namespace list" --wait 1m
```

### Start Workflow Execution

```bash
juju run temporal-admin-k8s/0 tctl args='workflow start --taskqueue test-queue --workflow_type GreetingWorkflow --input '\"World\"'' --wait 1m
```
