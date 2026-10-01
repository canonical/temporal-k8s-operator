# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Temporal charm pgbouncer integration tests."""

import logging

import jubilant
import pytest
from conftest import DEFAULT_WAIT_TIMEOUT, POSTGRESQL_CHANNEL, TEMPORAL_CHANNEL
from helpers import (
    APP_NAME,
    APP_NAME_ADMIN,
    PGBOUNCER_APP_NAME,
    PGBOUNCER_CHANNEL,
    POSTGRESQL_APP_NAME,
    create_default_namespace,
    fast_forward,
    run_sample_workflow,
    wait_active,
    wait_blocked,
)

logger = logging.getLogger(__name__)


@pytest.fixture(name="deploy", scope="module")
def deploy(juju: jubilant.Juju):
    """The app is up and running."""
    juju.wait_timeout = DEFAULT_WAIT_TIMEOUT

    # Deploy temporal server, temporal admin and postgresql charms.
    juju.deploy(APP_NAME, channel=TEMPORAL_CHANNEL, config={"num-history-shards": 1}, num_units=3)
    juju.deploy(POSTGRESQL_APP_NAME, channel=POSTGRESQL_CHANNEL, trust=True)
    juju.deploy(PGBOUNCER_APP_NAME, channel=PGBOUNCER_CHANNEL, trust=True)
    juju.deploy(APP_NAME_ADMIN, channel=TEMPORAL_CHANNEL)

    with fast_forward(juju):
        wait_blocked(juju, APP_NAME, APP_NAME_ADMIN, PGBOUNCER_APP_NAME, timeout=600)

        # Add integrations and wait for apps to become active and idle
        juju.integrate(PGBOUNCER_APP_NAME, POSTGRESQL_APP_NAME)
        juju.integrate(f"{APP_NAME}:db", f"{PGBOUNCER_APP_NAME}:database")
        juju.integrate(f"{APP_NAME}:visibility", f"{PGBOUNCER_APP_NAME}:database")
        juju.integrate(f"{APP_NAME}:admin", f"{APP_NAME_ADMIN}:admin")
        juju.integrate(f"{APP_NAME}:temporal-host-info", f"{APP_NAME_ADMIN}:temporal-host-info")
        wait_active(juju, timeout=90 * 10)

        # Run action to create default namespace
        create_default_namespace(juju)

        wait_active(juju, timeout=300)
        assert juju.status().apps[APP_NAME].units[f"{APP_NAME}/0"].is_active

    yield


@pytest.mark.abort_on_fail
@pytest.mark.usefixtures("deploy")
class TestPgbouncer:
    """Integration tests for Temporal charm."""

    def test_basic_client(self, juju: jubilant.Juju):
        """Connects a client and runs a basic Temporal workflow."""
        run_sample_workflow(juju)
