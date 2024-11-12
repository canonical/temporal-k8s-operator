# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Temporal charm scaling integration tests."""

import logging

import pytest
import pytest_asyncio
from helpers import (
    APP_NAME,
    APP_NAME_ADMIN,
    APP_NAME_UI,
    METADATA,
    create_default_namespace,
    run_sample_workflow,
    scale,
)
from pytest_operator.plugin import OpsTest

ALL_SERVICES = ["temporal-k8s", "temporal-k8s-history", "temporal-k8s-matching", "temporal-k8s-worker"]
ALL_CONFIG = ["frontend", "history", "matching", "worker"]

logger = logging.getLogger(__name__)


@pytest.mark.skip_if_deployed
@pytest_asyncio.fixture(name="deploy", scope="module")
async def deploy(ops_test: OpsTest):
    """The app is up and running."""
    charm = await ops_test.build_charm(".")
    resources = {"temporal-server-image": METADATA["resources"]["temporal-server-image"]["upstream-source"]}

    await ops_test.model.set_config({"update-status-hook-interval": "1m"})

    # Deploy temporal server, temporal admin and postgresql charms.
    for i in range(4):
        # for service in ALL_SERVICES:
        await ops_test.model.deploy(
            charm,
            resources=resources,
            application_name=ALL_SERVICES[i],
            config={"services": ALL_CONFIG[i], "num-history-shards": 1},
        )

    await ops_test.model.deploy(APP_NAME_ADMIN, channel="edge")
    await ops_test.model.deploy(APP_NAME_UI, channel="edge")
    await ops_test.model.deploy("postgresql-k8s", channel="14/stable", trust=True)
    await ops_test.model.deploy("pgbouncer-k8s", channel="1/stable", trust=True, config={"max_db_connections": 200})

    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(
            apps=[APP_NAME_ADMIN, APP_NAME_UI, "pgbouncer-k8s"] + ALL_SERVICES,
            status="blocked",
            raise_on_blocked=False,
            timeout=1200,
        )
        await ops_test.model.wait_for_idle(
            apps=["postgresql-k8s"], status="active", raise_on_blocked=False, timeout=1200
        )

        await ops_test.model.integrate("pgbouncer-k8s", "postgresql-k8s")

        await ops_test.model.wait_for_idle(
            apps=["postgresql-k8s", "pgbouncer-k8s"], status="active", raise_on_blocked=False, timeout=600
        )

        for service in ALL_SERVICES:
            assert ops_test.model.applications[service].units[0].workload_status == "blocked"

        # Must integrate temporal-k8s frontend service first
        await ops_test.model.integrate(f"{APP_NAME}:db", "pgbouncer-k8s:database")
        await ops_test.model.integrate(f"{APP_NAME}:visibility", "pgbouncer-k8s:database")
        await ops_test.model.integrate(f"{APP_NAME}:admin", f"{APP_NAME_ADMIN}:admin")
        await ops_test.model.wait_for_idle(apps=[APP_NAME], status="active", raise_on_blocked=False, timeout=600)

        for service in ALL_SERVICES:
            if service != "temporal-k8s":
                await ops_test.model.integrate(f"{service}:db", "pgbouncer-k8s:database")
                await ops_test.model.integrate(f"{service}:visibility", "pgbouncer-k8s:database")

        await ops_test.model.wait_for_idle(apps=ALL_SERVICES, status="active", raise_on_blocked=False, timeout=1800)

        await ops_test.model.integrate(f"{APP_NAME}:ui", f"{APP_NAME_UI}:ui")
        await ops_test.model.wait_for_idle(
            apps=[APP_NAME, APP_NAME_UI], status="active", raise_on_blocked=False, timeout=1200
        )

        await create_default_namespace(ops_test)

        await ops_test.model.wait_for_idle(apps=ALL_SERVICES, status="active", raise_on_blocked=False, timeout=1200)
        assert ops_test.model.applications["temporal-k8s"].units[0].workload_status == "active"

        await run_sample_workflow(ops_test)


@pytest.mark.abort_on_fail
@pytest.mark.usefixtures("deploy")
class TestScaling:
    """Integration tests for Temporal charm."""

    async def test_scaling_up(self, ops_test: OpsTest):
        """Scale Temporal charm up to 2 units."""
        for service in ALL_SERVICES:
            await scale(ops_test, app=service, units=2)

        await run_sample_workflow(ops_test, count=1000)

    async def test_scaling_down(self, ops_test: OpsTest):
        """Scale Temporal charm down to 1 unit."""
        for service in ALL_SERVICES:
            await scale(ops_test, app=service, units=1)

        await run_sample_workflow(ops_test, count=1000)
