#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd Ltd.
# See LICENSE file for licensing details.


"""Temporal client worker."""

import asyncio

from temporalio.client import Client
from temporalio.worker import Worker

from .activities import say_hello
from .workflows import SayHello


async def run_worker(url):
    """Temporal worker which connects to Temporal server.

    Args:
        url: Temporal server URL.
    """
    client = await Client.connect(url)

    # Run the worker
    worker = Worker(client, task_queue="my-task-queue", workflows=[SayHello], activities=[say_hello])
    await worker.run()


def sync_run_worker(url):
    """Asynchronous version of run_worker method.

    Args:
        url: Temporal server URL.
    """
    asyncio.run(run_worker(url))
