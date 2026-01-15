# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Temporal charm temporal-host-info relation integration tests."""

import logging
from pathlib import Path

import jubilant
import pytest
from helpers import APP_NAME

logger = logging.getLogger(__name__)


@pytest.fixture(scope="module")
def host_info_requirer(juju: jubilant.Juju) -> str | Path:
    """Fetch the path to charm."""
    charm = juju.build_charm("./tests/integration/host_info_requirer")
    assert charm, "Charm not built"
    return charm


@pytest.fixture(scope="module")
def juju(deploy: str):
    """Juju fixture for integration tests."""
    juju = jubilant.Juju(model=deploy)
    return juju


@pytest.mark.abort_on_fail
@pytest.mark.usefixtures("deploy")
class TestTemporalHostInfoRelation:
    """Tests for temporal-host-info relation."""

    def test_relation(self, juju: jubilant.Juju, host_info_requirer: str | Path):
        cfg = juju.config(APP_NAME)
        services = cfg["services"]["value"]
        new_cfg = {"external-hostname": "temporal.local.test"}
        if "frontend" not in services:
            services += ",frontend"
            new_cfg["services"] = services
        juju.config(APP_NAME, new_cfg)
        # Deploy host info requirer charm
        juju.deploy(
            host_info_requirer,
            application_name="host-info-requirer",
        )
        juju.wait(jubilant.all_active, timeout=300)
        juju.integrate("host-info-requirer:temporal-host-info", f"{APP_NAME}:temporal-host-info")
        juju.wait(jubilant.all_active, timeout=300)
        status = juju.status()
        requirer_unit = status.apps["host-info-requirer"].units["host-info-requirer/0"]
        expected_status = "Temporal host: temporal.local.test, port: 7233"
        assert requirer_unit.workload_status == "active"
        assert requirer_unit.workload_status_message == expected_status
