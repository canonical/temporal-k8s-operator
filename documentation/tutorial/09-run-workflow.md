# Run Your First Workflow

This is part of the [Charmed Temporal Tutorial](./01-introduction.md). Please
refer to this page for more information and the overview of the content.

Now that we have a Temporal Server up and running with a Temporal Worker
connected to it, we can trigger a workflow execution and observe its result in
the Web UI.

To do so, we can create the following simple client, which triggers the named
workflow `GreetingWorkflow` defined in the worker.

```python
from temporallib.client import Client, Options
import asyncio

async def main():
    client_opt = Options(
        host="10.1.232.64:7233", # Replace with your Temporal Server unit IP address
        queue="test-queue",
        namespace="default",
    )

    client = await Client.connect(client_opt=client_opt)
    workflow_name = "GreetingWorkflow"
    workflow_id = "hello-activity-workflow-id"

    greeting = await client.execute_workflow(
        workflow_name,
        "World",
        id=workflow_id,
        task_queue="test-queue",
    )

    logger.info(f"Greeting: {greeting}")


if __name__ == "__main__":
    asyncio.run(main())
```

Install the necessary packages and run the script above using:

```bash
pip install temporal-lib-py

python workflow.py

# Output:
Greeting: Hello, World!
```

Further details on the workflow execution can be viewed on the web UI.

Note: Workflow and activity payloads can be encrypted by setting the same key in
the `encryption-key` config of the Temporal worker and the `client_opt` in the
code above.

If using a TLS connection through ingress, you must provide the certificate
generated in the ingress step of this tutorial as part of your
[TLSConfig](https://python.temporal.io/temporalio.service.TLSConfig.html) when
making requests to the Temporal server.

> **See next: [Cleanup your environment](./10-cleanup.md)**
