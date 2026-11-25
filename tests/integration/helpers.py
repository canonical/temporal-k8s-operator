#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Temporal charm integration test helpers."""

import asyncio
import contextlib
import datetime
import json
import logging
import pathlib
import time
import uuid

import jubilant
import tenacity
import yaml
from google.protobuf.duration_pb2 import Duration
from temporal_client.activities import say_hello
from temporal_client.workflows import SayHello
from temporalio.api.workflowservice.v1 import (
    ListWorkflowExecutionsRequest,
    RegisterNamespaceRequest,
)
from temporalio.client import Client, WorkflowFailureError
from temporalio.service import RPCError, RPCStatusCode
from temporalio.worker import Worker

try:
    import temporal_sdk_bridge
except ImportError:  # integration extra not installed (e.g. lint-only env)
    temporal_sdk_bridge = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(pathlib.Path("./metadata.yaml").read_text())
APP_NAME = METADATA["name"]
APP_NAME_ADMIN = "temporal-admin-k8s"
APP_NAME_UI = "temporal-ui-k8s"
PGBOUNCER_APP_NAME = "pgbouncer-k8s"
POSTGRESQL_APP_NAME = "postgresql-k8s"
PGBOUNCER_CHANNEL = "1/stable"

ALLOWED = "allowed"
DENIED = "denied"


@contextlib.contextmanager
def fast_forward(juju: jubilant.Juju, interval: str = "10s"):
    """Temporarily shorten the update-status hook interval.

    Replacement for ``OpsTest.fast_forward``, which Jubilant has no equivalent of.

    Args:
        juju: Jubilant Juju object.
        interval: Hook interval to apply inside the context.
    """
    config = juju.model_config() or {}
    previous = config.get("update-status-hook-interval", "5m")
    juju.model_config({"update-status-hook-interval": interval})
    try:
        yield
    finally:
        juju.model_config({"update-status-hook-interval": previous})


def wait_active(juju: jubilant.Juju, *apps: str, timeout: float | None = None, successes: int = 3, error=None):
    """Wait until the given apps are active and their agents idle.

    Equivalent of ``wait_for_idle(apps=apps, status="active")``.

    Args:
        juju: Jubilant Juju object.
        apps: Applications to wait for. If empty, every app in the model is checked.
        timeout: Overall deadline in seconds.
        successes: Consecutive polls the condition must hold for
        error: Optional predicate that aborts the wait early.
    """
    juju.wait(
        lambda status: jubilant.all_active(status, *apps) and jubilant.all_agents_idle(status, *apps),
        error=error,
        successes=successes,
        timeout=timeout,
    )


def wait_blocked(juju: jubilant.Juju, *apps: str, timeout: float | None = None, successes: int = 3):
    """Wait until the given apps are blocked and their agents idle.

    Equivalent of ``wait_for_idle(apps=apps, status="blocked")``.

    Args:
        juju: Jubilant Juju object.
        apps: Applications to wait for. If empty, every app in the model is checked.
        timeout: Overall deadline in seconds.
        successes: Consecutive polls the condition must hold for
    """
    juju.wait(
        lambda status: jubilant.all_blocked(status, *apps) and jubilant.all_agents_idle(status, *apps),
        successes=successes,
        timeout=timeout,
    )


def assert_unit_active(juju: jubilant.Juju, *apps: str, unit: int = 0):
    """Assert the given unit of each app reports an active workload status.

    Args:
        juju: Jubilant Juju object.
        apps: Applications whose unit should be active.
        unit: Unit number to check.
    """
    status = juju.status()
    for app in apps:
        assert status.apps[app].units[f"{app}/{unit}"].is_active, f"{app}/{unit} is not active"


def run_action(juju: jubilant.Juju, unit: str, action: str, **params) -> jubilant.Task:
    """Run an action and return its task, even if the action failed.

    python-libjuju never raised on a failed action; callers below assert conditionally
    on ``task.status``, so the Jubilant ``TaskError`` is unwrapped to keep that behaviour.

    Args:
        juju: Jubilant Juju object.
        unit: Unit to run the action on.
        action: Action name.
        params: Action parameters; ``None`` values are omitted.

    Returns:
        The action task.
    """
    given = {key: value for key, value in params.items() if value is not None}
    try:
        return juju.run(unit, action, given)
    except jubilant.TaskError as exc:
        return exc.task


def scale(juju: jubilant.Juju, app: str, units: int):
    """Scale the application to the provided number and wait for idle.

    Args:
        juju: Jubilant Juju object.
        app: Application to be scaled.
        units: Number of units required.
    """
    juju.cli("scale-application", app, str(units))

    # Wait for model to settle
    juju.wait(
        lambda status: jubilant.all_active(status, app)
        and jubilant.all_agents_idle(status, app)
        and len(status.apps[app].units) == units,
        error=lambda status: jubilant.any_blocked(status, app),
        successes=30,
        timeout=600,
    )

    assert len(juju.status().apps[app].units) == units


def run_sample_workflow(juju: jubilant.Juju, count=1):
    """Connects a client and runs a basic Temporal workflow.

    Args:
        juju: Jubilant Juju object.
        count: Number of workflows to run.
    """
    # FIXME: change port back to 7233 when canonical/temporal-k8s-operator#152 is resolved
    url = get_application_url(juju, application=APP_NAME, port=7236)
    logger.info("running workflow on app address: %s", url)
    asyncio.run(_run_sample_workflow(url, count))


async def _run_sample_workflow(url: str, count=1):
    """Run the sample workflow against an already-resolved frontend address.

    Args:
        url: Temporal frontend address.
        count: Number of workflows to run.
    """
    client = await Client.connect(url)

    workflow_error_types: tuple = (WorkflowFailureError, RPCError)
    if temporal_sdk_bridge is not None:
        workflow_error_types = (WorkflowFailureError, RPCError, temporal_sdk_bridge.RPCError)

    def _retryable_workflow_error(exc: BaseException) -> bool:
        """Return True if the exception is retryable transient workflow/client errors."""
        if not isinstance(exc, workflow_error_types):
            return False
        message = str(exc).lower()
        return (
            "scheduletostart timeout" in message
            or "activity task timed out" in message
            or "timeout expired" in message
            or "not enough hosts" in message
            or "unavailable" in message
            or "workflow is busy" in message
            or "resource exhausted" in message
            or "resourceexhausted" in message
        )

    # Run a worker for the workflow
    start_time = time.time()
    async with Worker(client, task_queue="my-task-queue", workflows=[SayHello], activities=[say_hello]):
        name = "Jean-luc"
        for i in range(count):
            logger.info("running workflow #%d", i + 1)
            async for attempt in tenacity.AsyncRetrying(
                stop=tenacity.stop_after_attempt(5),
                wait=tenacity.wait_incrementing(start=10, increment=10),
                retry=tenacity.retry_if_exception(_retryable_workflow_error),
                reraise=True,
                before_sleep=tenacity.before_sleep_log(logger, logging.WARNING),
            ):
                with attempt:
                    result = await client.execute_workflow(
                        SayHello.run,
                        name,
                        id=f"my-workflow-id-{i}-{uuid.uuid4().hex[:12]}",
                        task_queue="my-task-queue",
                        execution_timeout=datetime.timedelta(seconds=300),
                    )
            logger.info(f"result: {result}")
        assert result == f"Hello, {name}!"

    end_time = time.time()
    logger.info(f"Finished executing {count} workflows in {end_time - start_time} seconds")


def create_default_namespace(juju: jubilant.Juju):
    """Creates default namespace on Temporal server using Temporal cli.

    Args:
        juju: Jubilant Juju object.
    """
    # Register default namespace from admin charm.
    task = juju.run(
        f"{APP_NAME_ADMIN}/0",
        "cli",
        {"args": "operator namespace create --namespace default --retention 3d"},
    )
    logger.info(f"cli result: {task.results}")
    assert task.return_code == 0
    if "result" in task.results:
        assert task.results["result"] == "command succeeded"


def get_application_url(juju: jubilant.Juju, application, port):
    """Returns application URL from the model.

    Args:
        juju: Jubilant Juju object.
        application: Name of the application.
        port: Port number of the URL.

    Returns:
        Application URL of the form {address}:{port}
    """
    address = juju.status().apps[application].address
    return f"{address}:{port}"


def get_unit_url(juju: jubilant.Juju, application, unit, port, protocol="http"):
    """Returns unit URL from the model.

    Args:
        juju: Jubilant Juju object.
        application: Name of the application.
        unit: Number of the unit.
        port: Port number of the URL.
        protocol: Transfer protocol (default: http).

    Returns:
        Unit URL of the form {protocol}://{address}:{port}
    """
    address = juju.status().apps[application].units[f"{application}/{unit}"].address
    return f"{protocol}://{address}:{port}"


def simulate_charm_crash(juju: jubilant.Juju, charm: pathlib.Path):
    """Simulates the Temporal charm crashing and being re-deployed.

    Args:
        juju: Jubilant Juju object.
        charm: Path to the locally packed temporal-k8s charm.
    """
    logger.info("simulating charm crash, removing temporal-k8s application")
    juju.remove_application(APP_NAME)
    juju.wait(lambda status: APP_NAME not in status.apps, timeout=600)

    resources = {"temporal-server-image": METADATA["resources"]["temporal-server-image"]["upstream-source"]}

    logger.info("re-deploying temporal-k8s application")
    juju.deploy(
        charm,
        APP_NAME,
        resources=resources,
        num_units=1,
        config={"num-history-shards": 1},
    )

    with fast_forward(juju):
        wait_blocked(juju, APP_NAME, timeout=600)

        logger.info("performing temporal charm integrations")
        perform_temporal_integrations(juju)


def perform_temporal_integrations(juju: jubilant.Juju):
    """Integrate Temporal charm with postgresql, admin and ui charms.

    Args:
        juju: Jubilant Juju object.
    """
    juju.integrate(f"{APP_NAME}:db", "postgresql-k8s:database")
    juju.integrate(f"{APP_NAME}:visibility", "postgresql-k8s:database")
    juju.integrate(f"{APP_NAME}:admin", f"{APP_NAME_ADMIN}:admin")
    juju.integrate(f"{APP_NAME}:temporal-host-info", f"{APP_NAME_ADMIN}:temporal-host-info")
    wait_active(juju, APP_NAME, timeout=1800)
    juju.integrate(f"{APP_NAME}:ui", f"{APP_NAME_UI}:ui")
    juju.integrate(f"{APP_NAME}:temporal-host-info", f"{APP_NAME_UI}:temporal-host-info")
    wait_active(juju, APP_NAME, APP_NAME_UI, timeout=1800)

    assert_unit_active(juju, APP_NAME)


def create_authorization_model(juju: jubilant.Juju):
    """Create the OpenFGA authorization model through the charm action.

    Args:
        juju: Jubilant Juju object.

    Raises:
        AssertionError: If the action never succeeds.
    """
    model_data = json.dumps(
        json.loads(pathlib.Path("./temporal_auth_model.json").read_text(encoding="utf-8")), separators=(",", ":")
    )
    for i in range(10):
        task = run_action(juju, f"{APP_NAME}/0", "create-authorization-model", model=model_data)
        logger.info(f"attempt {i} -> action result {task.status} {task.results}")
        if (
            task.status == "completed"
            and task.return_code == 0
            and task.results == {"result": "successfully created authorization model"}
        ):
            return
        time.sleep(2)
    raise AssertionError(f"create-authorization-model never succeeded: {task.status} {task.results}")


def perform_add_auth_rule_action(juju: jubilant.Juju, user=None, group=None, namespace=None, role=None):
    """Perform add-auth-rule action tests.

    Args:
        juju: Jubilant Juju object.
        user: User email.
        group: Group to assign membership to.
        namespace: Temporal namespace to assign access to.
        role: one of "reader", "writer" or "admin"
    """
    temporal_unit = f"{APP_NAME}/0"
    if user:
        task = run_action(juju, temporal_unit, "add-auth-rule", user=user, group=group)
    else:
        task = run_action(juju, temporal_unit, "add-auth-rule", group=group, namespace=namespace, role=role)

    if task.status == "completed":
        assert "output" in task.results


def perform_remove_auth_rule_action(juju: jubilant.Juju, user=None, group=None, namespace=None, role=None):
    """Perform remove-auth-rule action tests.

    Args:
        juju: Jubilant Juju object.
        user: User email.
        group: Group to remove membership from.
        namespace: Temporal namespace to remove access from.
        role: one of "reader", "writer" or "admin"
    """
    temporal_unit = f"{APP_NAME}/0"
    if user:
        task = run_action(juju, temporal_unit, "remove-auth-rule", user=user, group=group)
    else:
        task = run_action(juju, temporal_unit, "remove-auth-rule", group=group, namespace=namespace, role=role)

    if task.status == "completed":
        assert "output" in task.results


def perform_check_auth_rule_action(juju: jubilant.Juju, exp_result, user=None, group=None, namespace=None, role=None):
    """Perform check-auth-rule action tests.

    Args:
        juju: Jubilant Juju object.
        exp_result: The expected result of the check.
        user: User email.
        group: Group to check membership info for.
        namespace: Temporal namespace to check access for.
        role: one of "reader", "writer" or "admin"
    """
    temporal_unit = f"{APP_NAME}/0"
    if user:
        task = run_action(juju, temporal_unit, "check-auth-rule", user=user, group=group)
    else:
        task = run_action(juju, temporal_unit, "check-auth-rule", group=group, namespace=namespace, role=role)

    if task.status == "completed" and "output" in task.results:
        assert task.results["output"] == str(exp_result)


def perform_list_auth_rule_action(juju: jubilant.Juju, user=None, group=None, namespace=None):
    """Perform list-auth-rule action tests.

    Args:
        juju: Jubilant Juju object.
        user: User email.
        group: Group to list membership info for.
        namespace: Temporal namespace to list access info for.
    """
    temporal_unit = f"{APP_NAME}/0"
    if user:
        task = run_action(juju, temporal_unit, "list-auth-rule", user=user)
    elif group:
        task = run_action(juju, temporal_unit, "list-auth-rule", group=group)
    else:
        task = run_action(juju, temporal_unit, "list-auth-rule", namespace=namespace)

    if user:
        if task.status == "completed" and "output" in task.results:
            assert (
                task.results["output"]["member"] == "['group:test_group']"
                and task.results["output"]["reader"] == "['namespace:test_namespace']"
            )
    elif group:
        if task.status == "completed" and "output" in task.results:
            assert task.results["output"]["reader"] == "['namespace:test_namespace']"
    else:
        if task.status == "completed" and "output" in task.results:
            assert task.results["output"]["reader"] == "['group:test_group']"


def perform_list_system_admins_action(juju: jubilant.Juju):
    """Perform list-system-admins action tests.

    Args:
        juju: Jubilant Juju object.
    """
    task = run_action(juju, f"{APP_NAME}/0", "list-system-admins")

    assert task.status == "completed" and "output" in task.results
    assert (
        task.results["output"]["red"] == "['admin_one@example.com']"
        and task.results["output"]["green"] == "['admin_two@example.com']"
    )


def unit_frontend(juju: jubilant.Juju, unit: str, port: int = 7233) -> str:
    """Return the gRPC address of a unit's frontend.

    Args:
        juju: Jubilant Juju object.
        unit: Temporal unit name.
        port: gRPC port.

    Returns:
        Address of the form {ip}:{port}.
    """
    return f"{juju.status().apps[APP_NAME].units[unit].address}:{port}"


def _is_permission_denied(err: BaseException) -> bool:
    """Return whether an error is a Temporal PermissionDenied response.

    Args:
        err: Error raised by the Temporal client.

    Returns:
        True for PermissionDenied.
    """
    if isinstance(err, RPCError):
        return err.status == RPCStatusCode.PERMISSION_DENIED
    # Client.connect surfaces connection-time RPC failures as a RuntimeError.
    message = str(err)
    return isinstance(err, RuntimeError) and ("PermissionDenied" in message or "Request unauthorized" in message)


async def _perform(target: str, namespace: str, operation: str, metadata: dict[str, str]):
    """Connect and perform a single operation.

    Args:
        target: Frontend gRPC address.
        namespace: Namespace to operate on.
        operation: One of "list", "start" or "register_namespace".
        metadata: gRPC metadata to send.

    Raises:
        ValueError: If the operation is unknown.
    """
    client = await Client.connect(target, namespace=namespace, rpc_metadata=metadata)
    if operation == "list":
        await client.workflow_service.list_workflow_executions(
            ListWorkflowExecutionsRequest(namespace=namespace, page_size=1)
        )
    elif operation == "start":
        handle = await client.start_workflow(
            "SayHello",
            "auth",
            id=f"auth-{uuid.uuid4().hex[:12]}",
            task_queue="auth-test",
            execution_timeout=datetime.timedelta(minutes=1),
        )
        await handle.terminate("auth test cleanup")
    elif operation == "register_namespace":
        await client.workflow_service.register_namespace(
            RegisterNamespaceRequest(
                namespace=f"auth-{uuid.uuid4().hex[:12]}",
                workflow_execution_retention_period=Duration(seconds=86400),
            )
        )
    else:
        raise ValueError(f"unknown operation {operation}")


def probe(target: str, namespace: str, operation: str, token: str | None = None, header: str | None = None) -> str:
    """Perform an operation against a frontend and classify the outcome.

    Transient connect/transport errors are retried and then re-raised, so a
    broken server is never mistaken for an authorization decision. Any other
    non-permission error is raised immediately.

    Args:
        target: Frontend gRPC address.
        namespace: Namespace to operate on.
        operation: One of "list", "start" or "register_namespace".
        token: Bearer token to send, if any.
        header: Raw authorization header value; overrides token.

    Returns:
        ALLOWED or DENIED.

    Raises:
        last_error: The non-authorization error seen on the final attempt.
    """
    metadata = {}
    if header is not None:
        metadata["authorization"] = header
    elif token is not None:
        metadata["authorization"] = f"Bearer {token}"

    last_error: BaseException | None = None
    for _ in range(12):
        try:
            asyncio.run(_perform(target, namespace, operation, metadata))
            result = ALLOWED
        except Exception as err:  # pylint: disable=broad-except
            if not _is_permission_denied(err):
                if not (
                    (isinstance(err, RPCError) and err.status == RPCStatusCode.UNAVAILABLE)
                    or (isinstance(err, RuntimeError) and ("connect" in str(err) or "transport" in str(err)))
                ):
                    raise
                logger.warning("probe %s %s on %s: transient error %s", operation, namespace, target, err)
                last_error = err
                asyncio.run(asyncio.sleep(10))
                continue
            result = DENIED
        logger.info(
            "probe target=%s namespace=%s operation=%s token=%s header=%s -> %s",
            target, namespace, operation, token is not None, header is not None, result,
        )  # fmt: skip
        return result
    assert last_error is not None
    raise last_error
