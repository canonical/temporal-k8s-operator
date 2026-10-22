# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Scenario tests for the restart action."""

import ops.testing
import pytest
from ops import pebble


@pytest.fixture
def container_with_service():
    return ops.testing.Container(
        "temporal",
        can_connect=True,
        layers={
            "temporal": pebble.Layer(
                {
                    "services": {
                        "temporal-server": {
                            "override": "replace",
                            "command": "temporal-server start",
                            "startup": "enabled",
                        },
                    },
                }
            ),
        },
        service_statuses={"temporal-server": pebble.ServiceStatus.ACTIVE},
    )


def test_restart_action_restarts_the_pebble_service(context, container_with_service):
    """The action restarts the temporal-server Pebble service, not a container-named one."""
    state = ops.testing.State(containers={container_with_service}, leader=True)

    state_out = context.run(context.on.action("restart"), state)

    container = state_out.get_container("temporal")
    assert container.service_statuses["temporal-server"] == pebble.ServiceStatus.ACTIVE
    assert isinstance(state_out.unit_status, ops.ActiveStatus)


def test_restart_action_reports_restarting_status(context, container_with_service):
    """The unit reports Maintenance('restarting temporal') while the service restarts."""
    state = ops.testing.State(containers={container_with_service}, leader=True)

    context.run(context.on.action("restart"), state)

    assert ops.MaintenanceStatus("restarting temporal") in context.unit_status_history
