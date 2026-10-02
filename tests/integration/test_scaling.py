# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Temporal charm scaling integration tests."""

import logging
import pathlib

import jubilant
import pytest
from conftest import POSTGRESQL_CHANNEL, TEMPORAL_CHANNEL
from helpers import (
    APP_NAME,
    APP_NAME_ADMIN,
    APP_NAME_UI,
    PGBOUNCER_APP_NAME,
    PGBOUNCER_CHANNEL,
    POSTGRESQL_APP_NAME,
    assert_unit_active,
    create_default_namespace,
    fast_forward,
    run_sample_workflow,
    scale,
    wait_active,
    wait_blocked,
)

ALL_SERVICES = ["temporal-k8s", "temporal-k8s-history", "temporal-k8s-matching", "temporal-k8s-worker"]
ALL_CONFIG = ["frontend", "history", "matching", "worker"]

_SCALE_TEST_WORKFLOW_COUNT = 150

logger = logging.getLogger(__name__)


@pytest.fixture(name="deploy", scope="module")
def deploy(juju: jubilant.Juju, charm: pathlib.Path, charm_resources: dict):
    """The app is up and running."""
    juju.model_config({"update-status-hook-interval": "1m"})

    # Deploy temporal server, temporal admin and postgresql charms.
    for i in range(4):
        juju.deploy(
            charm,
            ALL_SERVICES[i],
            resources=charm_resources,
            config={
                "services": ALL_CONFIG[i],
                "num-history-shards": 1,
                "persistence-max-conns": 3,
                "persistence-max-idle-conns": 3,
                "visibility-max-conns": 5,
                "visibility-max-idle-conns": 5,
            },
        )

    juju.deploy(APP_NAME_ADMIN, channel=TEMPORAL_CHANNEL)
    juju.deploy(APP_NAME_UI, channel=TEMPORAL_CHANNEL)
    juju.deploy(POSTGRESQL_APP_NAME, channel=POSTGRESQL_CHANNEL, trust=True)
    juju.deploy(PGBOUNCER_APP_NAME, channel=PGBOUNCER_CHANNEL, trust=True, config={"max_db_connections": 20})

    with fast_forward(juju):
        wait_blocked(juju, APP_NAME_ADMIN, APP_NAME_UI, PGBOUNCER_APP_NAME, *ALL_SERVICES, timeout=1200)
        wait_active(juju, POSTGRESQL_APP_NAME, timeout=1200)

        juju.integrate(PGBOUNCER_APP_NAME, POSTGRESQL_APP_NAME)

        wait_active(juju, POSTGRESQL_APP_NAME, PGBOUNCER_APP_NAME, timeout=1200)

        status = juju.status()
        for service in ALL_SERVICES:
            assert status.apps[service].units[f"{service}/0"].is_blocked

        # Must integrate temporal-k8s frontend service first
        juju.integrate(f"{APP_NAME}:db", f"{PGBOUNCER_APP_NAME}:database")
        juju.integrate(f"{APP_NAME}:visibility", f"{PGBOUNCER_APP_NAME}:database")
        juju.integrate(f"{APP_NAME}:admin", f"{APP_NAME_ADMIN}:admin")
        juju.integrate(f"{APP_NAME}:temporal-host-info", f"{APP_NAME_ADMIN}:temporal-host-info")
        wait_active(juju, APP_NAME, timeout=600)

        for service in ALL_SERVICES:
            if service != "temporal-k8s":
                juju.integrate(f"{service}:db", f"{PGBOUNCER_APP_NAME}:database")
                juju.integrate(f"{service}:visibility", f"{PGBOUNCER_APP_NAME}:database")

        wait_active(juju, *ALL_SERVICES, timeout=1800)

        juju.integrate(f"{APP_NAME}:ui", f"{APP_NAME_UI}:ui")
        juju.integrate(f"{APP_NAME}:temporal-host-info", f"{APP_NAME_UI}:temporal-host-info")
        wait_active(juju, APP_NAME, APP_NAME_UI, timeout=1200)

        create_default_namespace(juju)

        wait_active(juju, *ALL_SERVICES, timeout=1200)
        assert_unit_active(juju, APP_NAME)

        run_sample_workflow(juju)

    yield


@pytest.mark.abort_on_fail
@pytest.mark.usefixtures("deploy")
class TestScaling:
    """Integration tests for Temporal charm."""

    def test_scaling_up(self, juju: jubilant.Juju):
        """Scale Temporal charm up to 2 units."""
        for service in ALL_SERVICES:
            scale(juju, app=service, units=2)

        # The count argument is an arbitrary number, keep it around 150 to allow
        # runners to complete this number of runs before timeouts.
        run_sample_workflow(juju, count=_SCALE_TEST_WORKFLOW_COUNT)

    def test_scaling_down(self, juju: jubilant.Juju):
        """Scale Temporal charm down to 1 unit."""
        for service in ALL_SERVICES:
            scale(juju, app=service, units=1)

        run_sample_workflow(juju, count=_SCALE_TEST_WORKFLOW_COUNT)
