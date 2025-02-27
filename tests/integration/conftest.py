# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Temporal charm integration test config."""

import asyncio
import logging
from pathlib import Path

import pytest_asyncio
from helpers import (
    APP_NAME,
    APP_NAME_ADMIN,
    APP_NAME_UI,
    METADATA,
    create_default_namespace,
    perform_temporal_integrations,
)
from pytest import FixtureRequest
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)


@pytest_asyncio.fixture(scope="module", name="charm")
async def charm_fixture(request: FixtureRequest, ops_test: OpsTest) -> str | Path:
    """Fetch the path to charm."""
    charms = request.config.getoption("--charm-file")
    if not charms:
        charm = await ops_test.build_charm(".")
        assert charm, "Charm not built"
        return charm
    return charms[0]


@pytest_asyncio.fixture(name="deploy", scope="module")
async def deploy(ops_test: OpsTest, charm: str):
    """The app is up and running."""
    resources = {"temporal-server-image": METADATA["resources"]["temporal-server-image"]["upstream-source"]}

    # Deploy temporal server, temporal admin and postgresql charms.
    asyncio.gather(
        ops_test.model.deploy(
            charm,
            resources=resources,
            application_name=APP_NAME,
            config={
                "num-history-shards": 1,
                "global-rps-limit": 100,
                "namespace-rps-limit": "default:50|test:40",
            },
        ),
        ops_test.model.deploy(APP_NAME_ADMIN, channel="edge"),
        ops_test.model.deploy(APP_NAME_UI, channel="edge"),
        ops_test.model.deploy("postgresql-k8s", channel="14/stable", trust=True),
        ops_test.model.deploy("self-signed-certificates", channel="latest/stable"),
    )

    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(
            apps=["postgresql-k8s", "self-signed-certificates"], status="active", raise_on_blocked=False, timeout=1200
        )

        await ops_test.model.integrate("self-signed-certificates", "postgresql-k8s")
        await ops_test.model.wait_for_idle(
            apps=["postgresql-k8s", "self-signed-certificates"], status="active", raise_on_blocked=False, timeout=1200
        )
        await ops_test.model.wait_for_idle(
            apps=[APP_NAME, APP_NAME_ADMIN, APP_NAME_UI], status="blocked", raise_on_blocked=False, timeout=600
        )

        await perform_temporal_integrations(ops_test)

        await create_default_namespace(ops_test)

        await ops_test.model.wait_for_idle(apps=[APP_NAME], status="active", raise_on_blocked=False, timeout=300)
        assert ops_test.model.applications[APP_NAME].units[0].workload_status == "active"
        assert ops_test.model.applications[APP_NAME_UI].units[0].workload_status == "active"
