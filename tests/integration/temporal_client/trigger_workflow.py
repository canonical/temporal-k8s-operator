# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Temporal client workflow runner."""

from temporalio.client import Client

from .workflows import SayHello


async def trigger_workflow(url, name):
    """Triggers a temporal workflow.

    Args:
        url: Temporal server URL.
        name: used to run the dynamic activity.

    Returns:
        Result of running workflow in the form "Hello, {name}!"
    """
    client = await Client.connect(url)

    # Execute a workflow
    result = await client.execute_workflow(SayHello.run, name, id="my-workflow-id", task_queue="my-task-queue")

    return result
