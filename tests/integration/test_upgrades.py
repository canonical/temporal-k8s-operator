# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Temporal charm upgrades integration tests."""

import logging
import pathlib
import time

import jubilant
import pytest
import requests
from conftest import DEFAULT_WAIT_TIMEOUT, POSTGRESQL_CHANNEL, TEMPORAL_CHANNEL
from helpers import (
    APP_NAME,
    APP_NAME_ADMIN,
    APP_NAME_UI,
    create_default_namespace,
    fast_forward,
    get_unit_url,
    perform_temporal_integrations,
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
    juju.deploy(APP_NAME, channel=TEMPORAL_CHANNEL, config={"num-history-shards": 1})
    juju.deploy(APP_NAME_ADMIN, channel=TEMPORAL_CHANNEL)
    juju.deploy(APP_NAME_UI, channel=TEMPORAL_CHANNEL)
    juju.deploy("postgresql-k8s", channel=POSTGRESQL_CHANNEL, trust=True, revision=381)

    with fast_forward(juju):
        wait_blocked(juju, APP_NAME, APP_NAME_ADMIN, APP_NAME_UI, timeout=600)
        wait_active(juju, "postgresql-k8s", timeout=600)

        perform_temporal_integrations(juju)

        create_default_namespace(juju)

        wait_active(juju, APP_NAME, timeout=300)
        status = juju.status()
        assert status.apps[APP_NAME].units[f"{APP_NAME}/0"].is_active
        assert status.apps[APP_NAME_UI].units[f"{APP_NAME_UI}/0"].is_active

    yield


@pytest.mark.skip("Skipping because of canonical/temporal-k8s-operator/issues/150")
@pytest.mark.abort_on_fail
@pytest.mark.usefixtures("deploy")
class TestUpgrade:
    """Integration test for Temporal charm upgrade from previous release."""

    def test_upgrade(self, juju: jubilant.Juju, charm: pathlib.Path, charm_resources: dict):
        """Builds the current charm and refreshes the current deployment."""
        wait_active(juju, APP_NAME, timeout=600)

        # This is to accmmodate for a self-resolving error which sometimes appears when Temporal
        # services attempt to connect to the cluster before the application is ready.
        # --base carries the 22.04->24.04 platform upgrade; refresh raises on failure.
        juju.refresh(APP_NAME, path=charm, resources=charm_resources, base="ubuntu@24.04")

        wait_active(juju, APP_NAME, timeout=600)
        time.sleep(10)

        with fast_forward(juju):
            # Delay time for application to settle. This is to accommodate for unit
            # becoming active while application is still waiting.
            time.sleep(10)
            assert juju.status().apps[APP_NAME].units[f"{APP_NAME}/0"].is_active

            run_sample_workflow(juju)

    def test_ui_relation(self, juju: jubilant.Juju):
        """Perform GET request on the Temporal UI host."""
        url = get_unit_url(juju, application=APP_NAME_UI, unit=0, port=8080)
        logger.info("curling app address: %s", url)

        response = requests.get(url, timeout=300)
        assert response.status_code == 200
