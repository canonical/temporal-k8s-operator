# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Temporal charm upgrades integration tests."""

import json
import logging
import re
import time
from pathlib import Path

import pytest
import pytest_asyncio
import requests
from conftest import POSTGRESQL_CHANNEL, TEMPORAL_CHANNEL
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


ADMIN_TARGET_CHANNEL = "1.26/edge"


def _read_workload_version() -> str:
    """Read WORKLOAD_VERSION out of src/literals.py without importing ops.

    The integration test environment does not install this charm's own
    package, so we parse the constant directly out of the source file instead
    of importing it.
    """
    text = Path("src/literals.py").read_text()
    match = re.search(r'^WORKLOAD_VERSION\s*=\s*"([^"]+)"', text, re.MULTILINE)
    assert match, "WORKLOAD_VERSION constant not found in src/literals.py"
    return match.group(1)


async def _get_admin_schema_version(ops_test: OpsTest) -> str | None:
    """Fetch the migrated_workload_version admin publishes over the admin relation."""
    retcode, stdout, stderr = await ops_test.juju(
        "show-unit", f"{APP_NAME}/0", "--format", "json", "-m", ops_test.model.name
    )
    assert retcode == 0, f"show-unit failed: {stderr}"
    data = json.loads(stdout)
    relation_info = data[f"{APP_NAME}/0"].get("relation-info", [])
    for relation in relation_info:
        if relation.get("endpoint") == "admin":
            return relation.get("application-data", {}).get("migrated_workload_version")
    return None


@pytest.mark.skip_if_deployed
@pytest_asyncio.fixture(name="deploy", scope="module")
async def deploy(ops_test: OpsTest):
    """The app is up and running."""
    # Deploy temporal server, temporal admin and postgresql charms.
    await ops_test.model.deploy(APP_NAME, channel=TEMPORAL_CHANNEL, config={"num-history-shards": 1})
    await ops_test.model.deploy(APP_NAME_ADMIN, channel=TEMPORAL_CHANNEL)
    await ops_test.model.deploy(APP_NAME_UI, channel=TEMPORAL_CHANNEL)
    await ops_test.model.deploy("postgresql-k8s", channel=POSTGRESQL_CHANNEL, trust=True, revision=381)

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
        resources = {"temporal-server-image": METADATA["resources"]["temporal-server-image"]["upstream-source"]}

        await ops_test.model.wait_for_idle(apps=[APP_NAME], status="active", raise_on_blocked=False, timeout=600)

        model_name = ops_test.model.name

        # Refresh admin first and wait for the schema migration to complete.
        # The server's post-upgrade schema-gate will block forever waiting for
        # a matching migrated_workload_version if admin is refreshed after.
        retcode, stdout, stderr = await ops_test.juju(
            "refresh",
            APP_NAME_ADMIN,
            "--channel",
            ADMIN_TARGET_CHANNEL,
            "-m",
            model_name,
        )
        assert retcode == 0, f"Admin refresh failed: {stderr}"

        await ops_test.model.wait_for_idle(
            apps=[APP_NAME_ADMIN], raise_on_error=False, status="active", raise_on_blocked=False, timeout=600
        )

        # This is to accommodate for a self-resolving error which sometimes appears when Temporal
        # services attempt to connect to the cluster before the application is ready.
        # Use CLI directly to support --base parameter for 22.04→24.04 platform upgrade
        retcode, stdout, stderr = await ops_test.juju(
            "refresh",
            APP_NAME,
            "--path",
            str(charm),
            "--resource",
            f"temporal-server-image={resources['temporal-server-image']}",
            "--base",
            "ubuntu@24.04",
            "-m",
            model_name,
        )
        assert retcode == 0, f"Refresh failed: {stderr}"

        await ops_test.model.wait_for_idle(
            apps=[APP_NAME], raise_on_error=False, status="active", raise_on_blocked=False, timeout=600
        )
        time.sleep(10)

        async with ops_test.fast_forward():
            # Delay time for application to settle. This is to accommodate for unit
            # becoming active while application is still waiting.
            time.sleep(10)
            assert ops_test.model.applications[APP_NAME].units[0].workload_status == "active"

            # Version-sync guard: fail loudly (rather than leaving the server
            # silently blocked) if admin's published schema_version doesn't
            # match this charm's own WORKLOAD_VERSION.
            admin_schema_version = await _get_admin_schema_version(ops_test)
            assert admin_schema_version == _read_workload_version(), (
                f"admin published migrated_workload_version={admin_schema_version!r} which does not match "
                f"this charm's WORKLOAD_VERSION={_read_workload_version()!r}; ADMIN_TARGET_CHANNEL "
                "in this test and WORKLOAD_VERSION in src/literals.py must be bumped together"
            )

            await run_sample_workflow(ops_test)

    async def test_ui_relation(self, ops_test: OpsTest):
        """Perform GET request on the Temporal UI host."""
        url = await get_unit_url(ops_test, application=APP_NAME_UI, unit=0, port=8080)
        logger.info("curling app address: %s", url)

        response = requests.get(url, timeout=300)
        assert response.status_code == 200
