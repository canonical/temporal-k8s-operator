# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Temporal charm scaling integration tests."""

import logging

import pytest
import pytest_asyncio
from helpers import (
    APP_NAME,
    APP_NAME_ADMIN,
    METADATA,
    create_default_namespace,
    run_sample_workflow,
)
from pytest_operator.plugin import OpsTest

ALL_SERVICES = ["temporal-k8s", "temporal-k8s-history", "temporal-k8s-matching", "temporal-k8s-worker"]
ALL_SERVICES_2 = ["temporal-k8s-history", "temporal-k8s-matching", "temporal-k8s-worker"]

logger = logging.getLogger(__name__)


@pytest.mark.skip_if_deployed
@pytest_asyncio.fixture(name="deploy", scope="module")
async def deploy(ops_test: OpsTest):
    """The app is up and running."""
    charm = await ops_test.build_charm(".")
    resources = {"temporal-server-image": METADATA["containers"]["temporal"]["upstream-source"]}

    # Deploy temporal server, temporal admin and postgresql charms.
    await ops_test.model.deploy(charm, resources=resources, application_name="temporal-k8s", num_units=1)
    await ops_test.model.deploy(charm, resources=resources, application_name="temporal-k8s-matching", num_units=1)
    await ops_test.model.deploy(charm, resources=resources, application_name="temporal-k8s-history", num_units=1)
    await ops_test.model.deploy(charm, resources=resources, application_name="temporal-k8s-worker", num_units=1)

    await ops_test.model.deploy(APP_NAME_ADMIN, channel="edge")
    await ops_test.model.deploy("postgresql-k8s", channel="14", trust=True)

    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(
            apps=[APP_NAME, APP_NAME_ADMIN], status="blocked", raise_on_blocked=False, timeout=1200
        )
        await ops_test.model.wait_for_idle(apps=ALL_SERVICES_2, status="blocked", raise_on_blocked=False, timeout=1200)
        await ops_test.model.wait_for_idle(
            apps=["postgresql-k8s"], status="active", raise_on_blocked=False, timeout=600
        )

        for service in ALL_SERVICES:
            assert ops_test.model.applications[service].units[0].workload_status == "blocked"

        await ops_test.model.integrate(f"{APP_NAME}:db", "postgresql-k8s:database")
        await ops_test.model.integrate(f"{APP_NAME}:visibility", "postgresql-k8s:database")
        await ops_test.model.integrate(f"{APP_NAME}:admin", f"{APP_NAME_ADMIN}:admin")
        await ops_test.model.wait_for_idle(apps=[APP_NAME], status="active", raise_on_blocked=False, timeout=180)

        for service in ALL_SERVICES_2:
            await ops_test.model.integrate(f"{service}:db", "postgresql-k8s:database")
            await ops_test.model.integrate(f"{service}:visibility", "postgresql-k8s:database")
            await ops_test.model.integrate(f"{service}:admin", f"{APP_NAME_ADMIN}:admin")

        await ops_test.model.wait_for_idle(apps=ALL_SERVICES, status="active", raise_on_blocked=False, timeout=1800)

        await create_default_namespace(ops_test)

        await ops_test.model.wait_for_idle(apps=ALL_SERVICES, status="active", raise_on_blocked=False, timeout=300)
        assert ops_test.model.applications["temporal-k8s"].units[0].workload_status == "active"

        application = ops_test.model.applications["temporal-k8s-matching"]
        await application.set_config({"services": "matching"})

        application = ops_test.model.applications["temporal-k8s"]
        await application.set_config({"services": "frontend"})

        application = ops_test.model.applications["temporal-k8s-history"]
        await application.set_config({"services": "history"})

        application = ops_test.model.applications["temporal-k8s-worker"]
        await application.set_config({"services": "worker"})

        await ops_test.model.wait_for_idle(apps=ALL_SERVICES, status="active", raise_on_blocked=False, timeout=600)


@pytest.mark.abort_on_fail
@pytest.mark.usefixtures("deploy")
class TestScaling:
    """Integration tests for Temporal charm."""

    async def test_scaling_up(self, ops_test: OpsTest):
        """Scale Temporal charm up to 2 units."""
        for service in ALL_SERVICES:
            await ops_test.model.applications[service].scale(scale=2)

        # Wait for model to settle
        await ops_test.model.wait_for_idle(
            apps=ALL_SERVICES,
            status="active",
            idle_period=30,
            raise_on_blocked=True,
            timeout=300,
            wait_for_exact_units=2,
        )

        for service in ALL_SERVICES:
            assert len(ops_test.model.applications[service].units) == 2

        await run_sample_workflow(ops_test)

    @pytest.mark.skip  # skip until scaling down operations work in MicroK8s. Units currently go into "Terminated" state and scale remains at 2.
    async def test_scaling_down(self, ops_test: OpsTest):
        """Scale Temporal charm down to 1 unit."""
        for service in ALL_SERVICES:
            await ops_test.model.applications[service].scale(scale=1)

        # Wait for model to settle
        await ops_test.model.wait_for_idle(
            apps=ALL_SERVICES,
            status="active",
            idle_period=30,
            raise_on_blocked=True,
            timeout=600,
            wait_for_exact_units=1,
        )

        assert len(ops_test.model.applications[service].units) == 1

        await run_sample_workflow(ops_test)
