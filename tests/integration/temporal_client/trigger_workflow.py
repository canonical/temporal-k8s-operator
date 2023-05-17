# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Temporal client workflow runner."""

import uuid

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
    result = await client.execute_workflow(
        SayHello.run, name, id=str(uuid.uuid1()), task_queue="my-task-queue", task_timeout=60
    )

    return result
