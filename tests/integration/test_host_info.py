# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Temporal charm temporal-host-info relation integration tests."""

import logging
import pathlib

import jubilant
import pytest
from helpers import APP_NAME, APP_NAME_ADMIN, APP_NAME_UI

logger = logging.getLogger(__name__)

_HOST_INFO_WAIT_APPS = (
    APP_NAME,
    APP_NAME_ADMIN,
    APP_NAME_UI,
    "postgresql-k8s",
    "self-signed-certificates",
    "host-info-requirer",
)


def _wait_stack_active(juju: jubilant.Juju, timeout: int = 900) -> None:
    """Wait until listed apps (and their units) report active workload and app status."""
    juju.wait(lambda s: jubilant.all_active(s, *_HOST_INFO_WAIT_APPS), timeout=timeout)


def _wait_requirer_agent_idle(juju: jubilant.Juju, timeout: int = 600) -> None:
    """Wait until the mock requirer's unit agent is idle (install/config hooks done)."""
    juju.wait(lambda s: jubilant.all_agents_idle(s, "host-info-requirer"), timeout=timeout)


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
        """Test host and port are correctly published when external-hostname is set."""
        cfg = juju.config(APP_NAME)
        services = cfg["services"]
        new_cfg = {"external-hostname": "temporal.local.test"}
        if "frontend" not in services:
            services += ",frontend"
            new_cfg["services"] = services
        juju.config(APP_NAME, new_cfg)
        # Deploy host info requirer charm
        juju.deploy(host_info_requirer_charm, "host-info-requirer")
        _wait_requirer_agent_idle(juju)
        juju.integrate("host-info-requirer:temporal-host-info", f"{APP_NAME}:temporal-host-info")
        _wait_stack_active(juju)
        status = juju.status()
        requirer_unit = status.apps["host-info-requirer"].units["host-info-requirer/0"]
        expected_status = "Temporal host: temporal.local.test, port: 7236"
        assert requirer_unit.workload_status.current == "active"
        assert requirer_unit.workload_status.message == expected_status

    def test_relation_no_ext_hostname(self, juju: jubilant.Juju):
        """Test host falls back to pod IP when external-hostname is unset."""
        juju.config(APP_NAME, {"external-hostname": ""})
        _wait_stack_active(juju)
        status = juju.status()
        requirer_unit = status.apps["host-info-requirer"].units["host-info-requirer/0"]
        server_ip = status.apps[APP_NAME].units[f"{APP_NAME}/0"].address
        expected_status = f"Temporal host: {server_ip}, port: 7236"
        assert requirer_unit.workload_status.current == "active"
        assert requirer_unit.workload_status.message == expected_status
