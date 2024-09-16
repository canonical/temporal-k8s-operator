# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Temporal charm upgrades integration tests."""

import asyncio
import logging
import time

import pytest
import pytest_asyncio
from helpers import (
    APP_NAME,
    APP_NAME_ADMIN,
    APP_NAME_UI,
    create_default_namespace,
    perform_temporal_integrations,
    run_sample_workflow,
)
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)

@pytest.mark.skip # TODO (kelkawi-a): investigate bug with test https://github.com/canonical/temporal-k8s-operator/actions/runs/10886756137/job/30209211247
@pytest.mark.skip_if_deployed
@pytest_asyncio.fixture(name="deploy", scope="module")
async def deploy(ops_test: OpsTest):
    """The app is up and running."""
    await ops_test.model.set_config({"update-status-hook-interval": "1m"})
    charm = await ops_test.build_charm(".")

    # Deploy Temporal server, Temporal admin, Temporal UI and postgresql charms.
    asyncio.gather(
        ops_test.model.deploy(
            charm,
            application_name=APP_NAME,
            resources={"temporal-server-image": "temporalio/server:1.20.0"},
            config={"num-history-shards": "1"},
        ),
        ops_test.model.deploy(
            APP_NAME_ADMIN, channel="edge", resources={"temporal-admin-image": "temporalio/admin-tools:1.20.0"}
        ),
        ops_test.model.deploy(APP_NAME_UI, channel="edge"),
        ops_test.model.deploy("postgresql-k8s", channel="14/stable", trust=True),
    )

    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(
            apps=[APP_NAME, APP_NAME_ADMIN, APP_NAME_UI], status="blocked", raise_on_blocked=False, timeout=600
        )
        await ops_test.model.wait_for_idle(
            apps=["postgresql-k8s"], status="active", raise_on_blocked=False, timeout=600
        )

        await perform_temporal_integrations(ops_test)

        await create_default_namespace(ops_test)

        await ops_test.model.wait_for_idle(apps=[APP_NAME], status="active", raise_on_blocked=False, timeout=300)
        assert ops_test.model.applications[APP_NAME].units[0].workload_status == "active"
        assert ops_test.model.applications[APP_NAME_UI].units[0].workload_status == "active"
        await run_sample_workflow(ops_test)


@pytest.mark.skip
@pytest.mark.abort_on_fail
@pytest.mark.usefixtures("deploy")
class TestServerUpgrade:
    """Integration test for Temporal server upgrade requiring schema update.

    This test ensures that upgrading from v1.20.0 to v1.21.2 (which requires a schema update) runs
    successfully on the newly built charm.
    """

    async def test_server_upgrade(self, ops_test: OpsTest):
        """Refresh the charm with a new resource which requires a schema update."""
        # Update admin charm to v1.21.2 first
        await ops_test.model.applications[APP_NAME_ADMIN].destroy()
        await ops_test.model.block_until(lambda: APP_NAME_ADMIN not in ops_test.model.applications)
        await ops_test.model.deploy(
            APP_NAME_ADMIN, channel="edge", resources={"temporal-admin-image": "temporalio/admin-tools:1.21.2"}
        )
        await ops_test.model.wait_for_idle(
            apps=[APP_NAME_ADMIN], raise_on_error=False, status="active", raise_on_blocked=False, timeout=600
        )

        admin_unit = ops_test.model.applications[APP_NAME_ADMIN].units[0]
        action = await admin_unit.run_action("setup-schema")
        await action.wait()

        # Needed for a local charm refresh
        charm = await ops_test.build_charm(".")

        # Update server charm to v1.21.2
        await ops_test.model.applications[APP_NAME].destroy()
        await ops_test.model.block_until(lambda: APP_NAME not in ops_test.model.applications)
        await ops_test.model.deploy(
            charm,
            application_name=APP_NAME,
            resources={"temporal-server-image": "temporalio/server:1.21.2"},
            config={"num-history-shards": "1"},
        )

        await perform_temporal_integrations(ops_test)

        # This is to accmmodate for a self-resolving error which sometimes appears when Temporal
        # services attempt to connect to the cluster before the application is ready.
        await ops_test.model.wait_for_idle(
            apps=[APP_NAME], raise_on_error=False, status="active", raise_on_blocked=False, timeout=600
        )
        time.sleep(10)

        assert ops_test.model.applications[APP_NAME].units[0].workload_status == "active"
        assert ops_test.model.applications[APP_NAME_ADMIN].units[0].workload_status == "active"

        await run_sample_workflow(ops_test)
