#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Temporal charm integration test helpers."""

import logging
from pathlib import Path

import yaml
from pytest_operator.plugin import OpsTest
from temporal_client.activities import say_hello
from temporal_client.workflows import GreetingWorkflow, SayHello
from temporalio.client import Client
from temporalio.worker import Worker

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
APP_NAME = METADATA["name"]
APP_NAME_ADMIN = "temporal-admin-k8s"
APP_NAME_UI = "temporal-ui-k8s"


async def scale(ops_test: OpsTest, app, units):
    """Scale the application to the provided number and wait for idle.

    Args:
        ops_test: PyTest object.
        app: Application to be scaled.
        units: Number of units required.
    """
    await ops_test.model.applications[app].scale(scale=units)

    # Wait for model to settle
    await ops_test.model.wait_for_idle(
        apps=[app],
        status="active",
        idle_period=30,
        raise_on_blocked=True,
        timeout=300,
        wait_for_exact_units=units,
    )

    assert len(ops_test.model.applications[app].units) == units


async def run_sample_workflow(ops_test: OpsTest):
    """Connects a client and runs a basic Temporal workflow.

    Args:
        ops_test: PyTest object.
    """
    url = await get_application_url(ops_test, application=APP_NAME, port=7233)
    logger.info("running workflow on app address: %s", url)

    client = await Client.connect(url)

    # Run a worker for the workflow
    async with Worker(client, task_queue="my-task-queue", workflows=[SayHello], activities=[say_hello]):
        name = "Jean-luc"
        result = await client.execute_workflow(SayHello.run, name, id="my-workflow-id", task_queue="my-task-queue")
        logger.info(f"result: {result}")
        assert result == f"Hello, {name}!"


async def run_signal_workflow(ops_test: OpsTest):
    """Connects a client and runs a basic Temporal workflow.

    Args:
        ops_test: PyTest object.
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

        await _simulate_charm_crash(ops_test)

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


async def create_default_namespace(ops_test: OpsTest):
    """Creates default namespace on Temporal server using tctl.

    Args:
        ops_test: PyTest object.
    """
    # Register default namespace from admin charm.
    action = (
        await ops_test.model.applications[APP_NAME_ADMIN]
        .units[0]
        .run_action("tctl", args="--ns default namespace register -rd 3")
    )
    result = (await action.wait()).results
    logger.info(f"tctl result: {result}")
    assert "result" in result and result["result"] == "command succeeded"


async def get_application_url(ops_test: OpsTest, application, port):
    """Returns application URL from the model.

    Args:
        ops_test: PyTest object.
        application: Name of the application.
        port: Port number of the URL.

    Returns:
        Application URL of the form {address}:{port}
    """
    status = await ops_test.model.get_status()  # noqa: F821
    address = status["applications"][application].public_address
    return f"{address}:{port}"


async def get_unit_url(ops_test: OpsTest, application, unit, port, protocol="http"):
    """Returns unit URL from the model.

    Args:
        ops_test: PyTest object.
        application: Name of the application.
        unit: Number of the unit.
        port: Port number of the URL.
        protocol: Transfer protocol (default: http).

    Returns:
        Unit URL of the form {protocol}://{address}:{port}
    """
    status = await ops_test.model.get_status()  # noqa: F821
    address = status["applications"][application]["units"][f"{APP_NAME_UI}/{unit}"]["address"]
    return f"{protocol}://{address}:{port}"


async def _simulate_charm_crash(ops_test: OpsTest):
    """Simulates the Temporal charm crashing and being re-deployed.

    Args:
        ops_test: PyTest object.
    """
    await ops_test.model.applications[APP_NAME].destroy(force=True)
    await ops_test.model.block_until(lambda: APP_NAME not in ops_test.model.applications)

    charm = await ops_test.build_charm(".")
    resources = {"temporal-server-image": METADATA["containers"]["temporal"]["upstream-source"]}

    # Deploy temporal server, temporal admin and postgresql charms.
    await ops_test.model.deploy(charm, resources=resources, application_name=APP_NAME, num_units=1)

    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(apps=[APP_NAME], status="blocked", raise_on_blocked=False, timeout=600)

        await perform_temporal_integrations(ops_test)


async def perform_temporal_integrations(ops_test: OpsTest):
    """Integrate Temporal charm with postgresql, admin and ui charms.

    Args:
        ops_test: PyTest object.
    """
    await ops_test.model.integrate(f"{APP_NAME}:db", "postgresql-k8s:database")
    await ops_test.model.integrate(f"{APP_NAME}:visibility", "postgresql-k8s:database")
    await ops_test.model.integrate(f"{APP_NAME}:admin", f"{APP_NAME_ADMIN}:admin")
    await ops_test.model.wait_for_idle(apps=[APP_NAME], status="active", raise_on_blocked=False, timeout=180)
    await ops_test.model.integrate(f"{APP_NAME}:ui", f"{APP_NAME_UI}:ui")
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME, APP_NAME_UI], status="active", raise_on_blocked=False, timeout=180
    )

    assert ops_test.model.applications[APP_NAME].units[0].workload_status == "active"
