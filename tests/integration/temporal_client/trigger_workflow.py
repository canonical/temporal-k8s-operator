#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd Ltd.
# See LICENSE file for licensing details.

from temporalio.client import Client

from .workflows import SayHello


async def trigger_workflow(url, name):
    client = await Client.connect(url)

    # Execute a workflow
    result = await client.execute_workflow(SayHello.run, name, id="my-workflow-id", task_queue="my-task-queue")

    return result
