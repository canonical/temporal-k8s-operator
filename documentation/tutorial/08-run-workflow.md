# Run Your First Workflow

This is part of the
[Charmed Temporal Tutorial](https://discourse.charmhub.io/t/charmed-temporal-k8s-tutorial-introduction/11777).
Please refer to this page for more information and the overview of the content.

Now that we have a Temporal Server up and running with a Temporal Worker
connected to it, we can trigger a workflow execution and observe its result in
the Web UI.

1. Create simple client to trigger the workflow as defined in the worker.
For instance, if using the Python SDK, this would be:

```python
from temporallib.client import Client, Options
import asyncio

async def main():
    client_opt = Options(
        host="<temporal-host-name>:7233",
        queue="<your-queue>",
        namespace="<your-namespace>",
    )

    client = await Client.connect(client_opt=client_opt)
    workflow_name = "<workflow-name>"
    workflow_id = "<workflow-id>"

    greeting = await client.execute_workflow(
        workflow_name,
        id=workflow_id,
        task_queue="<your-queue>",
    )


if __name__ == "__main__":
    asyncio.run(main())
```

2. Install the necessary packages and run the script above using:

```bash
pip install temporal-lib-py

python workflow.py
```

3. Further details on the workflow execution can be viewed on the web UI.

[note]

Workflow and activity payloads can be encrypted by setting the same key in
the `auth-secret-id` config of the Temporal worker and the Client configurations
provided by the various Temporal SDKs.
See [`auth-secret-id`](https://charmhub.io/temporal-worker-k8s/configurations#auth-secret-id) for details.

[/note]

[note]

If TLS termination on ingress is configured, the Certificate Authority (CA) certificate must be also
provided to the Client. See [Temporal SDKs](https://docs.temporal.io/develop/) for configuration details.

[/note]

> **See next: [Cleanup your environment](https://discourse.charmhub.io/t/charmed-temporal-k8s-tutorial-cleanup-and-extra-info/11786)**
