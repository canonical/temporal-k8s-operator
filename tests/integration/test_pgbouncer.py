# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Temporal charm pgbouncer integration tests."""

import logging

import pytest
import pytest_asyncio
from helpers import (
    APP_NAME,
    APP_NAME_ADMIN,
    APP_NAME_UI,
    create_default_namespace,
    run_sample_workflow,
)
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)


@pytest.mark.skip_if_deployed
@pytest_asyncio.fixture(name="deploy", scope="module")
async def deploy(ops_test: OpsTest):
    """The app is up and running."""
    # Deploy temporal server, temporal admin and postgresql charms.
    await ops_test.model.deploy(APP_NAME, channel="edge", config={"num-history-shards": 1})
    await ops_test.model.deploy(APP_NAME_ADMIN, channel="edge")
    await ops_test.model.deploy(APP_NAME_UI, channel="edge")
    await ops_test.model.deploy("postgresql-k8s", channel="14/stable", trust=True)
    await ops_test.model.deploy("pgbouncer-k8s", channel="1/stable", trust=True)

    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(
            apps=[APP_NAME, APP_NAME_ADMIN, APP_NAME_UI, "pgbouncer-k8s"],
            status="blocked",
            raise_on_blocked=False,
            timeout=600,
        )
        await ops_test.model.wait_for_idle(
            apps=["postgresql-k8s"], status="active", raise_on_blocked=False, timeout=600
        )

        await ops_test.model.integrate("pgbouncer-k8s", "postgresql-k8s")

        await ops_test.model.wait_for_idle(
            apps=["postgresql-k8s", "pgbouncer-k8s"], status="active", raise_on_blocked=False, timeout=600
        )

        await ops_test.model.integrate(f"{APP_NAME}:db", "pgbouncer-k8s:database")
        await ops_test.model.integrate(f"{APP_NAME}:visibility", "pgbouncer-k8s:database")
        await ops_test.model.integrate(f"{APP_NAME}:admin", f"{APP_NAME_ADMIN}:admin")
        await ops_test.model.wait_for_idle(apps=[APP_NAME], status="active", raise_on_blocked=False, timeout=180)
        await ops_test.model.integrate(f"{APP_NAME}:ui", f"{APP_NAME_UI}:ui")
        await ops_test.model.wait_for_idle(
            apps=[APP_NAME, APP_NAME_UI], status="active", raise_on_blocked=False, timeout=180
        )

        assert ops_test.model.applications[APP_NAME].units[0].workload_status == "active"

        await create_default_namespace(ops_test)

        await ops_test.model.wait_for_idle(apps=[APP_NAME], status="active", raise_on_blocked=False, timeout=300)
        assert ops_test.model.applications[APP_NAME].units[0].workload_status == "active"
        assert ops_test.model.applications[APP_NAME_UI].units[0].workload_status == "active"


@pytest.mark.abort_on_fail
@pytest.mark.usefixtures("deploy")
class TestPgbouncer:
    """Integration tests for Temporal charm."""

    async def test_basic_client(self, ops_test: OpsTest):
        """Connects a client and runs a basic Temporal workflow."""
        await run_sample_workflow(ops_test)
