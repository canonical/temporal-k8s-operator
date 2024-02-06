#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Temporal charm integration test helpers."""

import logging
from pathlib import Path

import yaml
from pytest_operator.plugin import OpsTest
from temporal_client.activities import say_hello
from temporal_client.workflows import SayHello
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
        timeout=600,
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
    address = status["applications"][application]["units"][f"{application}/{unit}"]["address"]
    return f"{protocol}://{address}:{port}"


async def simulate_charm_crash(ops_test: OpsTest):
    """Simulates the Temporal charm crashing and being re-deployed.

    Args:
        ops_test: PyTest object.
    """
    await ops_test.model.applications[APP_NAME].destroy()
    await ops_test.model.block_until(lambda: APP_NAME not in ops_test.model.applications)

    charm = await ops_test.build_charm(".")
    resources = {"temporal-server-image": METADATA["containers"]["temporal"]["upstream-source"]}

    # Deploy temporal server, temporal admin and postgresql charms.
    await ops_test.model.deploy(
        charm, resources=resources, application_name=APP_NAME, num_units=1, config={"num-history-shards": 1}
    )

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


async def perform_add_auth_rule_action(ops_test: OpsTest, user=None, group=None, namespace=None, role=None):
    """Perform add-auth-rule action tests.

    Args:
        ops_test: PyTest object.
        user: User email.
        group: Group to assign membership to.
        namespace: Temporal namespace to assign access to.
        role: one of "reader", "writer" or "admin"
    """
    temporal_unit = ops_test.model.applications[APP_NAME].units[0]
    if user:
        action = await temporal_unit.run_action("add-auth-rule", user=user, group=group)
    else:
        action = await temporal_unit.run_action("add-auth-rule", group=group, namespace=namespace, role=role)

    result = await action.wait()
    if result.status == "completed":
        assert "output" in result.results


async def perform_remove_auth_rule_action(ops_test: OpsTest, user=None, group=None, namespace=None, role=None):
    """Perform remove-auth-rule action tests.

    Args:
        ops_test: PyTest object.
        user: User email.
        group: Group to remove membership from.
        namespace: Temporal namespace to remove access from.
        role: one of "reader", "writer" or "admin"
    """
    temporal_unit = ops_test.model.applications[APP_NAME].units[0]
    if user:
        action = await temporal_unit.run_action("remove-auth-rule", user=user, group=group)
    else:
        action = await temporal_unit.run_action("remove-auth-rule", group=group, namespace=namespace, role=role)

    result = await action.wait()
    if result.status == "completed":
        assert "output" in result.results


async def perform_check_auth_rule_action(
    ops_test: OpsTest, exp_result, user=None, group=None, namespace=None, role=None
):
    """Perform check-auth-rule action tests.

    Args:
        ops_test: PyTest object.
        exp_result: The expected result of the check.
        user: User email.
        group: Group to check membership info for.
        namespace: Temporal namespace to check access for.
        role: one of "reader", "writer" or "admin"
    """
    temporal_unit = ops_test.model.applications[APP_NAME].units[0]
    if user:
        action = await temporal_unit.run_action("check-auth-rule", user=user, group=group)
    else:
        action = await temporal_unit.run_action("check-auth-rule", group=group, namespace=namespace, role=role)

    result = await action.wait()
    if result.status == "completed" and "output" in result.results:
        assert result.results["output"] == str(exp_result)


async def perform_list_auth_rule_action(ops_test: OpsTest, user=None, group=None, namespace=None):
    """Perform list-auth-rule action tests.

    Args:
        ops_test: PyTest object.
        user: User email.
        group: Group to list membership info for.
        namespace: Temporal namespace to list access info for.
    """
    temporal_unit = ops_test.model.applications[APP_NAME].units[0]
    if user:
        action = await temporal_unit.run_action("list-auth-rule", user=user)
    elif group:
        action = await temporal_unit.run_action("list-auth-rule", group=group)
    else:
        action = await temporal_unit.run_action("list-auth-rule", namespace=namespace)

    result = await action.wait()
    if user:
        if result.status == "completed" and "output" in result.results:
            assert (
                result.results["output"]["member"] == "['group:test_group']"
                and result.results["output"]["reader"] == "['namespace:test_namespace']"
            )
    elif group:
        if result.status == "completed" and "output" in result.results:
            assert result.results["output"]["reader"] == "['namespace:test_namespace']"
    else:
        if result.status == "completed" and "output" in result.results:
            assert result.results["output"]["reader"] == "['group:test_group']"


async def perform_list_system_admins_action(ops_test: OpsTest):
    """Perform list-system-admins action tests.

    Args:
        ops_test: PyTest object.
    """
    temporal_unit = ops_test.model.applications[APP_NAME].units[0]
    action = await temporal_unit.run_action("list-system-admins")
    result = await action.wait()

    assert result.status == "completed" and "output" in result.results
    assert (
        result.results["output"]["red"] == "['admin_one@example.com']"
        and result.results["output"]["green"] == "['admin_two@example.com']"
    )
