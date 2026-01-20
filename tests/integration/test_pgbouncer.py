# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Temporal charm pgbouncer integration tests."""

import logging

import pytest
import pytest_asyncio
from conftest import POSTGRESQL_CHANNEL, TEMPORAL_CHANNEL
from helpers import (
    APP_NAME,
    APP_NAME_ADMIN,
    PGBOUNCER_APP_NAME,
    PGBOUNCER_CHANNEL,
    POSTGRESQL_APP_NAME,
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
    await ops_test.model.deploy(APP_NAME, channel=TEMPORAL_CHANNEL, config={"num-history-shards": 1}, num_units=3)
    await ops_test.model.deploy(POSTGRESQL_APP_NAME, channel=POSTGRESQL_CHANNEL, trust=True)
    await ops_test.model.deploy(PGBOUNCER_APP_NAME, channel=PGBOUNCER_CHANNEL, trust=True)
    await ops_test.model.deploy(APP_NAME_ADMIN, channel=TEMPORAL_CHANNEL)

    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(
            apps=[APP_NAME, APP_NAME_ADMIN, PGBOUNCER_APP_NAME],
            status="blocked",
            raise_on_blocked=False,
            timeout=600,
        )

        # Add integrations and wait for apps to become active and idle
        await ops_test.model.integrate(PGBOUNCER_APP_NAME, POSTGRESQL_APP_NAME)
        await ops_test.model.integrate(f"{APP_NAME}:db", f"{PGBOUNCER_APP_NAME}:database")
        await ops_test.model.integrate(f"{APP_NAME}:visibility", f"{PGBOUNCER_APP_NAME}:database")
        await ops_test.model.integrate(f"{APP_NAME}:admin", f"{APP_NAME_ADMIN}:admin")
        await ops_test.model.wait_for_idle(status="active", raise_on_blocked=False, timeout=90 * 10)

        # Run action to create default namespace
        await create_default_namespace(ops_test)

        await ops_test.model.wait_for_idle(status="active", raise_on_blocked=False, timeout=300)
        assert ops_test.model.applications[APP_NAME].units[0].workload_status == "active"


@pytest.mark.abort_on_fail
@pytest.mark.usefixtures("deploy")
class TestPgbouncer:
    """Integration tests for Temporal charm."""

    async def test_basic_client(self, ops_test: OpsTest):
        """Connects a client and runs a basic Temporal workflow."""
        await run_sample_workflow(ops_test)
