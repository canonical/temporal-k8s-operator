# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Temporal charm integration test config."""

import logging
import pathlib

import jubilant
import pytest
from helpers import (
    APP_NAME,
    APP_NAME_ADMIN,
    APP_NAME_UI,
    METADATA,
    create_default_namespace,
    fast_forward,
    perform_temporal_integrations,
    wait_active,
    wait_blocked,
)

logger = logging.getLogger(__name__)

TEMPORAL_CHANNEL = "1.31/edge"
POSTGRESQL_CHANNEL = "14/stable"
SELF_SIGNED_CERTIFICATES_CHANNEL = "1/stable"

# python-libjuju's default, preserved for waits that pass no explicit timeout.
DEFAULT_WAIT_TIMEOUT = 10 * 60


@pytest.fixture(scope="module", name="charm")
def charm_fixture(request: pytest.FixtureRequest) -> pathlib.Path:
    """Return the path to the locally packed temporal-k8s charm.

    Uses ``--charm-file`` when provided, otherwise requires exactly one ``*.charm``
    in the project root (``tox -e integration`` packs it before invoking pytest).
    """
    if charms := request.config.getoption("--charm-file"):
        assert len(charms) == 1, f"expected a single --charm-file, got: {charms}"
        charm = pathlib.Path(charms[0])
    else:
        packed = sorted(pathlib.Path(".").glob("*.charm"))
        assert packed, "*.charm not found in project root; pack the charm first (charmcraft pack)"
        assert len(packed) == 1, f"more than one *.charm in project root, unsure which to use: {packed}"
        charm = packed[0]

    charm = charm.resolve()
    assert charm.is_file(), f"{charm} is not a file"
    return charm


@pytest.fixture(scope="module", name="charm_resources")
def charm_resources_fixture() -> dict:
    """Return the resources for the locally built temporal-k8s charm."""
    return {"temporal-server-image": METADATA["resources"]["temporal-server-image"]["upstream-source"]}


@pytest.fixture(name="deploy", scope="module")
def deploy(juju: jubilant.Juju, charm: pathlib.Path, charm_resources: dict):
    """The app is up and running."""
    juju.wait_timeout = DEFAULT_WAIT_TIMEOUT

    # Deploy temporal server, temporal admin and postgresql charms.
    juju.deploy(
        charm,
        APP_NAME,
        resources=charm_resources,
        config={
            "num-history-shards": 1,
            "global-rps-limit": 100,
            "namespace-rps-limit": "default:50|test:40",
        },
    )
    juju.deploy(APP_NAME_ADMIN, channel=TEMPORAL_CHANNEL)
    juju.deploy(APP_NAME_UI, channel=TEMPORAL_CHANNEL)
    juju.deploy("postgresql-k8s", channel=POSTGRESQL_CHANNEL, trust=True)
    juju.deploy("self-signed-certificates", channel=SELF_SIGNED_CERTIFICATES_CHANNEL)

    with fast_forward(juju):
        wait_active(juju, "postgresql-k8s", "self-signed-certificates", timeout=1200)

        juju.integrate("postgresql-k8s:certificates", "self-signed-certificates:certificates")
        wait_active(juju, "postgresql-k8s", "self-signed-certificates", timeout=1200)

        wait_blocked(juju, APP_NAME, APP_NAME_ADMIN, APP_NAME_UI, timeout=600)

        perform_temporal_integrations(juju)

        create_default_namespace(juju)

        wait_active(juju, APP_NAME, timeout=300)
        status = juju.status()
        assert status.apps[APP_NAME].units[f"{APP_NAME}/0"].is_active
        assert status.apps[APP_NAME_UI].units[f"{APP_NAME_UI}/0"].is_active

    yield
