#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd Ltd.
# See LICENSE file for licensing details.

"""Temporal charm integration test config."""

import logging
from pathlib import Path

import pytest
import pytest_asyncio
import yaml
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
APP_NAME = METADATA["name"]
APP_NAME_ADMIN = "temporal-admin-k8s"


@pytest.mark.skip_if_deployed
@pytest_asyncio.fixture(name="deploy", scope="module")
async def deploy(ops_test: OpsTest):
    """The app is up and running."""
    charm = await ops_test.build_charm(".")
    resources = {"temporal-server-image": METADATA["containers"]["temporal"]["upstream-source"]}

    # Deploy temporal server, temporal admin and postgresql charms.
    await ops_test.model.deploy(charm, resources=resources, application_name=APP_NAME, num_units=1)
    await ops_test.model.deploy(APP_NAME_ADMIN, channel="edge")
    await ops_test.model.deploy("postgresql-k8s", channel="14", trust=True)

    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(
            apps=[APP_NAME, APP_NAME_ADMIN], status="blocked", raise_on_blocked=False, timeout=600
        )
        await ops_test.model.wait_for_idle(
            apps=["postgresql-k8s"], status="active", raise_on_blocked=False, timeout=600
        )

        assert ops_test.model.applications[APP_NAME].units[0].workload_status == "blocked"
        await ops_test.model.integrate(f"{APP_NAME}:db", "postgresql-k8s:database")
        await ops_test.model.integrate(f"{APP_NAME}:visibility", "postgresql-k8s:database")
        await ops_test.model.integrate(f"{APP_NAME}:admin", f"{APP_NAME_ADMIN}:admin")
        await ops_test.model.wait_for_idle(apps=[APP_NAME], status="active", raise_on_blocked=False, timeout=180)

        # Register default namespace from admin charm.
        action = (
            await ops_test.model.applications[APP_NAME_ADMIN]
            .units[0]
            .run_action("tctl", args="--ns default namespace register -rd 3")
        )
        result = (await action.wait()).results
        logger.info(f"tctl result: {result}")
        assert "result" in result and result["result"] == "command succeeded"

        await ops_test.model.wait_for_idle(apps=[APP_NAME], status="active", raise_on_blocked=False, timeout=300)
        assert ops_test.model.applications[APP_NAME].units[0].workload_status == "active"
