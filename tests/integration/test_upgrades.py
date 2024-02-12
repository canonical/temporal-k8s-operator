# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Temporal charm upgrades integration tests."""

import logging
import time

import pytest
import pytest_asyncio
import requests
from helpers import (
    APP_NAME,
    APP_NAME_ADMIN,
    APP_NAME_UI,
    METADATA,
    create_default_namespace,
    get_unit_url,
    perform_temporal_integrations,
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


@pytest.mark.abort_on_fail
@pytest.mark.usefixtures("deploy")
class TestUpgrade:
    """Integration test for Temporal charm upgrade from previous release."""

    async def test_upgrade(self, ops_test: OpsTest):
        """Builds the current charm and refreshes the current deployment."""
        charm = await ops_test.build_charm(".")
        resources = {"temporal-server-image": METADATA["containers"]["temporal"]["upstream-source"]}

        await ops_test.model.wait_for_idle(apps=[APP_NAME], status="active", raise_on_blocked=False, timeout=600)

        # This is to accmmodate for a self-resolving error which sometimes appears when Temporal
        # services attempt to connect to the cluster before the application is ready.
        await ops_test.model.applications[APP_NAME].refresh(path=str(charm), resources=resources)

        await ops_test.model.wait_for_idle(
            apps=[APP_NAME], raise_on_error=False, status="active", raise_on_blocked=False, timeout=600
        )
        time.sleep(10)

        async with ops_test.fast_forward():
            # Delay time for application to settle. This is to accommodate for unit
            # becoming active while application is still waiting.
            time.sleep(10)
            assert ops_test.model.applications[APP_NAME].units[0].workload_status == "active"

            await run_sample_workflow(ops_test)

    async def test_ui_relation(self, ops_test: OpsTest):
        """Perform GET request on the Temporal UI host."""
        url = await get_unit_url(ops_test, application=APP_NAME_UI, unit=0, port=8080)
        logger.info("curling app address: %s", url)

        response = requests.get(url, timeout=300)
        assert response.status_code == 200
