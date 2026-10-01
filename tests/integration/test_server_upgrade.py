# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Temporal charm upgrades integration tests."""

import logging
import pathlib
import time

import jubilant
import pytest
from conftest import DEFAULT_WAIT_TIMEOUT, POSTGRESQL_CHANNEL, TEMPORAL_CHANNEL
from helpers import (
    APP_NAME,
    APP_NAME_ADMIN,
    APP_NAME_UI,
    create_default_namespace,
    fast_forward,
    perform_temporal_integrations,
    run_sample_workflow,
    wait_active,
    wait_blocked,
)

logger = logging.getLogger(__name__)


@pytest.fixture(name="deploy", scope="module")
def deploy(juju: jubilant.Juju, charm: pathlib.Path):
    """The app is up and running."""
    juju.wait_timeout = DEFAULT_WAIT_TIMEOUT
    juju.model_config({"update-status-hook-interval": "1m"})

    # Deploy Temporal server, Temporal admin, Temporal UI and postgresql charms.
    juju.deploy(
        charm,
        APP_NAME,
        resources={"temporal-server-image": "temporalio/server:1.20.0"},
        config={"num-history-shards": "1"},
    )
    juju.deploy(
        APP_NAME_ADMIN,
        channel=TEMPORAL_CHANNEL,
        resources={"temporal-admin-image": "temporalio/admin-tools:1.20.0"},
    )
    juju.deploy(APP_NAME_UI, channel=TEMPORAL_CHANNEL)
    juju.deploy("postgresql-k8s", channel=POSTGRESQL_CHANNEL, trust=True)

    with fast_forward(juju):
        wait_blocked(juju, APP_NAME, APP_NAME_ADMIN, APP_NAME_UI, timeout=600)
        wait_active(juju, "postgresql-k8s", timeout=600)

        perform_temporal_integrations(juju)

        create_default_namespace(juju)

        wait_active(juju, APP_NAME, timeout=300)
        status = juju.status()
        assert status.apps[APP_NAME].units[f"{APP_NAME}/0"].is_active
        assert status.apps[APP_NAME_UI].units[f"{APP_NAME_UI}/0"].is_active
        run_sample_workflow(juju)

    yield


@pytest.mark.skip  # TODO (kelkawi-a): investigate bug with test https://github.com/canonical/temporal-k8s-operator/actions/runs/10886756137/job/30209211247
@pytest.mark.abort_on_fail
@pytest.mark.usefixtures("deploy")
class TestServerUpgrade:
    """Integration test for Temporal server upgrade requiring schema update.

    This test ensures that upgrading from v1.20.0 to v1.21.2 (which requires a schema update) runs
    successfully on the newly built charm.
    """

    def test_server_upgrade(self, juju: jubilant.Juju, charm: pathlib.Path):
        """Refresh the charm with a new resource which requires a schema update."""
        # Update admin charm to v1.21.2 first
        juju.remove_application(APP_NAME_ADMIN)
        juju.wait(lambda status: APP_NAME_ADMIN not in status.apps, timeout=600)
        juju.deploy(
            APP_NAME_ADMIN,
            channel=TEMPORAL_CHANNEL,
            resources={"temporal-admin-image": "temporalio/admin-tools:1.21.2"},
        )
        wait_active(juju, APP_NAME_ADMIN, timeout=600)

        juju.run(f"{APP_NAME_ADMIN}/0", "setup-schema")

        # Update server charm to v1.21.2
        juju.remove_application(APP_NAME)
        juju.wait(lambda status: APP_NAME not in status.apps, timeout=600)
        juju.deploy(
            charm,
            APP_NAME,
            resources={"temporal-server-image": "temporalio/server:1.21.2"},
            config={"num-history-shards": "1"},
        )

        perform_temporal_integrations(juju)

        # This is to accmmodate for a self-resolving error which sometimes appears when Temporal
        # services attempt to connect to the cluster before the application is ready.
        wait_active(juju, APP_NAME, timeout=600)
        time.sleep(10)

        status = juju.status()
        assert status.apps[APP_NAME].units[f"{APP_NAME}/0"].is_active
        assert status.apps[APP_NAME_ADMIN].units[f"{APP_NAME_ADMIN}/0"].is_active

        run_sample_workflow(juju)
