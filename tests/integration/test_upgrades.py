# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Temporal charm upgrades integration tests."""

import json
import logging
import pathlib
import re
from pathlib import Path

import jubilant
import pytest
import requests
from conftest import ADMIN_BASE, POSTGRESQL_CHANNEL, TEMPORAL_CHANNEL
from helpers import (
    APP_NAME,
    APP_NAME_ADMIN,
    APP_NAME_UI,
    assert_unit_active,
    create_default_namespace,
    fast_forward,
    get_unit_url,
    perform_temporal_integrations,
    run_sample_workflow,
    wait_active,
    wait_blocked,
)

logger = logging.getLogger(__name__)


PREVIOUS_TEMPORAL_CHANNEL = "1.30/edge"
ADMIN_TARGET_CHANNEL = TEMPORAL_CHANNEL


def _read_workload_version() -> str:
    """Read WORKLOAD_VERSION out of src/literals.py without importing ops.

    The integration test environment does not install this charm's own
    package, so we parse the constant directly out of the source file instead
    of importing it.
    """
    text = Path("src/literals.py").read_text()
    match = re.search(r'^WORKLOAD_VERSION\s*=\s*"([^"]+)"', text, re.MULTILINE)
    assert match, "WORKLOAD_VERSION constant not found in src/literals.py"
    return match.group(1)


def _get_admin_schema_data(juju: jubilant.Juju) -> dict:
    """Get schema status published by Admin."""
    unit = f"{APP_NAME}/0"
    data = json.loads(juju.cli("show-unit", unit, "--format", "json"))

    for relation in data[unit].get("relation-info", []):
        if relation.get("endpoint") == "admin":
            return relation.get("application-data", {})
    return {}


@pytest.fixture(name="deploy", scope="module")
def deploy(juju: jubilant.Juju):
    """The app is up and running."""
    # Deploy temporal server, temporal admin and postgresql charms.

    juju.deploy(
        APP_NAME,
        channel=PREVIOUS_TEMPORAL_CHANNEL,
        config={"num-history-shards": 1},
        base="ubuntu@24.04",
    )

    juju.deploy(
        APP_NAME_ADMIN,
        channel=PREVIOUS_TEMPORAL_CHANNEL,
        base="ubuntu@24.04",
    )

    juju.deploy(APP_NAME_UI, channel=TEMPORAL_CHANNEL)
    juju.deploy("postgresql-k8s", channel=POSTGRESQL_CHANNEL, trust=True, base="ubuntu@22.04")

    with fast_forward(juju):
        wait_blocked(juju, APP_NAME, APP_NAME_ADMIN, APP_NAME_UI, timeout=1800)
        wait_active(juju, "postgresql-k8s", timeout=1800)

        perform_temporal_integrations(juju)

        create_default_namespace(juju)

        wait_active(juju, APP_NAME, timeout=1800)
        assert_unit_active(juju, APP_NAME, APP_NAME_UI)

    yield


@pytest.mark.abort_on_fail
@pytest.mark.usefixtures("deploy")
class TestUpgrade:
    """Integration test for Temporal charm upgrade from previous release."""

    def test_upgrade(
        self,
        juju: jubilant.Juju,
        charm: pathlib.Path,
        charm_resources: dict,
    ):
        """Upgrade Server from 1.30 to local 1.31."""
        wait_active(juju, APP_NAME, timeout=1800)

        juju.refresh(
            APP_NAME_ADMIN,
            channel=ADMIN_TARGET_CHANNEL,
            base=ADMIN_BASE,
        )
        wait_active(juju, APP_NAME_ADMIN, timeout=1800)

        expected_version = _read_workload_version()

        juju.wait(
            lambda _: (
                _get_admin_schema_data(juju).get("migrated_workload_version") == expected_version
                and _get_admin_schema_data(juju).get("schema_status") == "ready"
            ),
            delay=5,
            timeout=1800,
        )

        juju.refresh(
            APP_NAME,
            path=charm,
            resources=charm_resources,
            base="ubuntu@26.04",
        )

        wait_active(juju, APP_NAME, timeout=1800)

        with fast_forward(juju):
            assert_unit_active(juju, APP_NAME)
            run_sample_workflow(juju)

    def test_ui_relation(self, juju: jubilant.Juju):
        """Perform GET request on the Temporal UI host."""
        url = get_unit_url(juju, application=APP_NAME_UI, unit=0, port=8080)
        logger.info("curling app address: %s", url)

        response = requests.get(url, timeout=1800)
        assert response.status_code == 200
