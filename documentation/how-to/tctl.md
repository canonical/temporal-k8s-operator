# Temporal CLI

[tctl](https://docs.temporal.io/tctl-v1) is a command-line tool that can be used
to interact with a Temporal Cluster.

The tool is available for use as an action in the Charmed Temporal Admin K8s
operator. Once deployed and related to the Temporal server, we can run any of
the available commands such as:

## Create Namespace

```bash
juju run temporal-admin-k8s/0 tctl args="--ns default namespace register -rd 3"
```

# List Namespaces

```bash
juju run temporal-admin-k8s/0 tctl args="namespace list"
```

## Start Workflow Execution

```bash
juju run temporal-admin-k8s/0 tctl args='workflow start --taskqueue test-queue --workflow_type GreetingWorkflow --input '\"World\"''
```
