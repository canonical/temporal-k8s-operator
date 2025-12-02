# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Temporal charm pgbouncer integration tests."""

import logging
from pathlib import Path

import pytest
import pytest_asyncio
from conftest import POSTGRESQL_CHANNEL, TEMPORAL_CHANNEL
from helpers import (
    APP_NAME,
    APP_NAME_ADMIN,
    PGBOUNCER_APP_NAME,
    PGBOUNCER_CHANNEL,
    METADATA,
    POSTGRESQL_APP_NAME,
    create_default_namespace,
    run_sample_workflow,
)
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)


@pytest_asyncio.fixture(scope="module")
async def host_info_requirer(ops_test: OpsTest) -> str | Path:
    """Fetch the path to charm."""
    charm = await ops_test.build_charm("./test/integration/host_info_requirer")
    assert charm, "Charm not built"
    return charm



@pytest.mark.abort_on_fail
@pytest.mark.usefixtures("deploy")
class TestTemporalHostInfoRelation:

    async def test_relation(self, ops_test: OpsTest, host_info_requirer: str | Path):
        cfg = await ops_test.model.applications[APP_NAME].get_config()
        services = cfg["services"]["value"]
        new_cfg = {"external-hostname": "temporal.local.test"}
        if "frontend" not in services:
            services += ",frontend"
            new_cfg["services"] = services
        await ops_test.model.applications[APP_NAME].set_config(
            new_cfg
        )
        # Deploy host info requirer charm
        await ops_test.model.deploy(
            host_info_requirer,
            application_name="host-info-requirer",
        )
        await ops_test.model.wait_for_idle(apps=["host-info-requirer"], status="waiting", raise_on_blocked=False, timeout=300)
        await ops_test.model.integrate("host-info-requirer:temporal-host-info", f"{APP_NAME}:temporal-host-info")
        await ops_test.model.wait_for_idle(apps=["host-info-requirer"], status="active", raise_on_blocked=False, timeout=300)
        requirer_app = ops_test.model.applications["host-info-requirer"]
        requirer_unit = requirer_app.units[0]
        expected_status = "Temporal host: temporal.local.test, port: 7233"
        assert requirer_unit.workload_status == "active"
        assert requirer_unit.workload_status_message == expected_status
