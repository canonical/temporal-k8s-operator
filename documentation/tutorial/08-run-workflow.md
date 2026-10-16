# Run Your First Workflow

This is part of the
[Charmed Temporal Tutorial](https://discourse.charmhub.io/t/charmed-temporal-k8s-tutorial-introduction/11777).
Please refer to this page for more information and the overview of the content.

Now that you have a Temporal Server up and running with a Temporal Worker
connected to it, you will trigger a workflow execution and observe its result in
the Web UI.

This tutorial uses the `GreetingWorkflow` workflow type registered by the
[`resource_sample_py`](https://github.com/canonical/temporal-worker-k8s-operator/tree/main/resource_sample_py)
sample worker image. If you used a different worker image, substitute the matching
workflow type. Other workflow types registered by the sample image include
`VaultWorkflow` and `DatabaseWorkflow`.

You can trigger a workflow either via the Temporal Python SDK (option A) or via the
admin charm's `cli` action (option B).

## Option A: trigger via the Python SDK

1. Create a client to trigger the workflow as defined in the worker. For instance, using the Canonical
[`temporal-lib-py`](https://pypi.org/project/temporal-lib-py/) wrapper:

```python
from temporallib.client import Client, Options
import asyncio

async def main():
    client_opt = Options(
        host="temporal-k8s.<model>.svc.cluster.local:7233",
        queue="your-queue",
        namespace="your-namespace",
    )

    client = await Client.connect(client_opt=client_opt)

    greeting = await client.execute_workflow(
        "GreetingWorkflow",
        "world",                     # workflow input (the name to greet)
        id="hello-1",
        task_queue="your-queue",
    )

    print(greeting)


if __name__ == "__main__":
    asyncio.run(main())
```

Replace:

* `<model>` with the Juju model name where `temporal-k8s` is deployed.
* `your-queue` and `your-namespace` with the values you set in the
  [Deploy Temporal Admin](https://discourse.charmhub.io/t/charmed-temporal-k8s-tutorial-deploy-temporal-admin/11781) and
  [Deploy Temporal Worker](https://discourse.charmhub.io/t/charmed-temporal-k8s-tutorial-deploy-temporal-worker/11784)
  steps.

2. Install the necessary packages and run the script as follows:

```bash
pip install temporal-lib-py

python workflow.py
```

## Option B: trigger via the admin charm's `cli` action

If you do not want to write Python, the admin charm exposes a `cli` action that wraps the modern [`temporal` CLI](https://docs.temporal.io/cli):

```bash
juju run temporal-admin-k8s/0 cli args="workflow start \
  --type GreetingWorkflow \
  --task-queue your-queue \
  --workflow-id hello-1 \
  --input '\"world\"' \
  --namespace your-namespace" --wait 1m
```

Verify the result:

```bash
juju run temporal-admin-k8s/0 cli args="workflow show \
  --workflow-id hello-1 \
  --namespace your-namespace" --wait 1m
```

You should see the workflow's full event history ending in `WorkflowExecutionCompleted` with status `COMPLETED`.

## View the workflow in the Web UI

Further details on the workflow execution can be viewed on the
[Temporal Web UI](https://discourse.charmhub.io/t/charmed-temporal-k8s-tutorial-deploy-temporal-web-ui/11782) you deployed earlier. Look up the workflow by ID (`hello-1` in the examples above) to see its event history, input, output, and timing.

[note]

Workflow and activity payloads can be encrypted by setting the same key in
the `auth-secret-id` config of the Temporal worker and the Client configurations
provided by the various Temporal SDKs.
See [`auth-secret-id`](https://charmhub.io/temporal-worker-k8s/configurations#auth-secret-id) for details.

[/note]

[note]

If TLS termination on ingress is configured, you must also provide the Certificate Authority (CA) to the client.
See [Temporal SDKs](https://docs.temporal.io/develop/) for configuration details.

[/note]

> **See next: [Cleanup your environment](https://discourse.charmhub.io/t/charmed-temporal-k8s-tutorial-cleanup-and-extra-info/11786)**
