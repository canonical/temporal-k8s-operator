#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Temporal charm integration tests."""

import logging

import pytest
import requests
from conftest import deploy  # noqa: F401, pylint: disable=W0611
from helpers import (
    APP_NAME,
    APP_NAME_UI,
    get_application_url,
    get_unit_url,
    run_sample_workflow,
    simulate_charm_crash,
)
from pytest_operator.plugin import OpsTest
from temporal_client.workflows import GreetingWorkflow
from temporalio.client import Client
from temporalio.worker import Worker

logger = logging.getLogger(__name__)


@pytest.mark.abort_on_fail
@pytest.mark.usefixtures("deploy")
class TestDeployment:
    """Integration tests for Temporal charm."""

    async def test_ui_relation(self, ops_test: OpsTest):
        """Perform GET request on the Temporal UI host."""
        url = await get_unit_url(ops_test, application=APP_NAME_UI, unit=0, port=8080)
        logger.info("curling app address: %s", url)

        response = requests.get(url, timeout=300)
        assert response.status_code == 200

    async def test_basic_client(self, ops_test: OpsTest):
        """Connects a client and runs a basic Temporal workflow."""
        await run_sample_workflow(ops_test, count=1000)

    async def test_charm_crash(self, ops_test: OpsTest):
        """Test backup and restore functionality.

        This tests the charm's ability to continue workflow execution after simulating
        a crash in the charm. Essentially, it should prove that the charm is stateless
        and relies only on the db to store its workflow execution status.
        """
        url = await get_application_url(ops_test, application=APP_NAME, port=7233)
        logger.info("running signal workflow on app address: %s", url)

        client = await Client.connect(url)

        # Run a worker for the workflow
        async with Worker(
            client,
            task_queue="hello-signal-task-queue",
            workflows=[GreetingWorkflow],
        ):

            # While the worker is running, use the client to start the workflow.
            # Note, in many production setups, the client would be in a completely
            # separate process from the worker.
            handle = await client.start_workflow(
                GreetingWorkflow.run,
                id="hello-signal-workflow-id",
                task_queue="hello-signal-task-queue",
            )

            # Send a few signals for names, then signal it to exit
            await handle.signal(GreetingWorkflow.submit_greeting, "user1")
            await handle.signal(GreetingWorkflow.submit_greeting, "user2")
            await handle.signal(GreetingWorkflow.submit_greeting, "user3")

            await simulate_charm_crash(ops_test)

            url = await get_application_url(ops_test, application=APP_NAME, port=7233)

            new_client = await Client.connect(url)
            handle = new_client.get_workflow_handle("hello-signal-workflow-id")

            async with Worker(
                new_client,
                task_queue="hello-signal-task-queue",
                workflows=[GreetingWorkflow],
            ):
                await handle.signal(GreetingWorkflow.submit_greeting, "user4")
                await handle.signal(GreetingWorkflow.exit)

                # Show result
                result = await handle.result()
                logger.info(f"Signal Result: {result}")
                assert result == ["Hello, user1", "Hello, user2", "Hello, user3", "Hello, user4"]
