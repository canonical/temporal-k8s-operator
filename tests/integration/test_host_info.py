# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Temporal charm temporal-host-info relation integration tests."""

import logging
import pathlib

import jubilant
import pytest
from conftest import deploy  # noqa: F401, pylint: disable=W0611
from helpers import APP_NAME, APP_NAME_ADMIN, APP_NAME_UI, wait_active

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
        """Test the in-cluster service FQDN and port are published."""
        cfg = juju.config(APP_NAME)
        services = cfg["services"]
        if "frontend" not in services:
            juju.config(APP_NAME, {"services": services + ",frontend"})
        # Deploy host info requirer charm
        juju.deploy(host_info_requirer_charm, "host-info-requirer")
        _wait_requirer_agent_idle(juju)
        juju.integrate("host-info-requirer:temporal-host-info", f"{APP_NAME}:temporal-host-info")
        _wait_stack_active(juju)
        status = juju.status()
        requirer_unit = status.apps["host-info-requirer"].units["host-info-requirer/0"]
        expected_status = f"Temporal host: {APP_NAME}.{juju.model}.svc.cluster.local, port: 7236, tls: False"
        assert requirer_unit.workload_status.current == "active"
        assert requirer_unit.workload_status.message == expected_status

    def test_relation_ignores_external_hostname(self, juju: jubilant.Juju):
        """Test external-hostname (nginx-route only) does not change the published host."""
        juju.config(APP_NAME, {"external-hostname": "temporal.local.test"})
        # Everything is already active here, so also wait for the agents to
        # settle: otherwise the assertion can run before config-changed is
        # handled and pass whether or not the host changed.
        wait_active(juju, *_HOST_INFO_WAIT_APPS, timeout=900)
        status = juju.status()
        requirer_unit = status.apps["host-info-requirer"].units["host-info-requirer/0"]
        expected_status = f"Temporal host: {APP_NAME}.{juju.model}.svc.cluster.local, port: 7236, tls: False"
        assert requirer_unit.workload_status.current == "active"
        assert requirer_unit.workload_status.message == expected_status
