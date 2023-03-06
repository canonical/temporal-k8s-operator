# Import the activity and workflow from our other files
from temporalio.client import Client
from .workflows import SayHello

async def run_workflow(url, name):
    client = await Client.connect(url)

    # Execute a workflow
    result = await client.execute_workflow(
        SayHello.run, name, id="my-workflow-id", task_queue="my-task-queue"
    )

    return result