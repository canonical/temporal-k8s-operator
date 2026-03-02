# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Temporal charm temporal-host-info relation integration tests."""

import logging
import pathlib

import jubilant
import pytest
from helpers import APP_NAME

logger = logging.getLogger(__name__)


@pytest.fixture(scope="module")
def juju(deploy: str):
    """Juju fixture for integration tests."""
    juju = jubilant.Juju(model=deploy)
    return juju


@pytest.fixture(scope="module")
def host_info_requirer_charm() -> pathlib.Path:
    """Return full absolute path to given test charm."""
    name = "temporal-host-info-requirer"
    charm_dir = pathlib.Path(__file__).parent / "host_info_requirer"
    charms = [p.absolute() for p in charm_dir.glob(f"{name}_*.charm")]
    assert charms, f"{name}_*.charm not found"
    assert len(charms) == 1, "more than one .charm file, unsure which to use"
    return charms[0]


@pytest.mark.abort_on_fail
@pytest.mark.usefixtures("deploy")
class TestTemporalHostInfoRelation:
    """Tests for temporal-host-info relation."""

    def test_relation(self, juju: jubilant.Juju, host_info_requirer_charm: pathlib.Path):
        cfg = juju.config(APP_NAME)
        services = cfg["services"]
        new_cfg = {"external-hostname": "temporal.local.test"}
        if "frontend" not in services:
            services += ",frontend"
            new_cfg["services"] = services
        juju.config(APP_NAME, new_cfg)
        # Deploy host info requirer charm
        juju.deploy(
            host_info_requirer_charm,
            "host-info-requirer",
            resources={"workload-image": "ghcr.io/canonical/api_demo_server:1.0.2"},
        )
        juju.wait(jubilant.all_active, timeout=300)
        juju.integrate("host-info-requirer:temporal-host-info", f"{APP_NAME}:temporal-host-info")
        juju.wait(jubilant.all_active, timeout=300)
        status = juju.status()
        requirer_unit = status.apps["host-info-requirer"].units["host-info-requirer/0"]
        expected_status = "Temporal host: temporal.local.test, port: 7233"
        assert requirer_unit.workload_status == "active"
        assert requirer_unit.workload_status.message == expected_status
