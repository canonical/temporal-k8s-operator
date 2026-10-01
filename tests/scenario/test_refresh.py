# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Refresh must wait for the target schema on every server role."""

import dataclasses

import ops
import ops.testing
import pytest


@pytest.mark.parametrize("leader", [True, False])
@pytest.mark.parametrize("services", ["frontend", "history", "matching", "worker"])
@pytest.mark.parametrize("status,version", [("ready", "1.23.1"), ("ready", ""), ("updating", "1.24.3"), ("failed", "")])
def test_stale_readiness_cannot_start_server(
    context, peer_relation, admin_relation, temporal_container, leader, services, status, version
):
    peer_relation.local_app_data["schema_ready"] = "true"
    admin_relation.remote_app_data.update(schema_status=status, schema_version=version)
    state = ops.testing.State(
        leader=leader,
        config={"num-history-shards": 1, "services": services},
        relations=[peer_relation, admin_relation],
        containers=[temporal_container],
    )
    result = context.run(context.on.upgrade_charm(), state)
    assert result.unit_status == ops.BlockedStatus("admin:temporal relation: schema is not ready")
    assert not result.get_container("temporal").plan.services


@pytest.mark.parametrize("leader", [True, False])
def test_ready_relation_starts_fresh_container(
    context, peer_relation, admin_relation, temporal_container, network, leader
):
    peer_relation.local_app_data["schema_ready"] = "true"
    state = ops.testing.State(
        leader=leader,
        config={"num-history-shards": 1},
        relations=[peer_relation, admin_relation],
        containers=[temporal_container],
        networks=[network],
    )
    result = context.run(context.on.upgrade_charm(), state)
    service = result.get_container("temporal").plan.services["temporal-server"]
    assert service.command.startswith("/bin/temporal-server-1.24.3 ")
    assert result.unit_status == ops.MaintenanceStatus("replanning application")


@pytest.mark.parametrize("leader", [True, False])
def test_ready_relation_resumes_waiting_unit(
    context, peer_relation, admin_relation, temporal_container, network, leader
):
    peer_relation.local_app_data["schema_ready"] = "true"
    admin_relation.remote_app_data.update(schema_status="updating", schema_version="")
    state = ops.testing.State(
        leader=leader,
        config={"num-history-shards": 1},
        relations=[peer_relation, admin_relation],
        containers=[temporal_container],
        networks=[network],
    )
    waiting = context.run(context.on.upgrade_charm(), state)
    ready = dataclasses.replace(
        waiting.get_relation(admin_relation.id), remote_app_data={"schema_status": "ready", "schema_version": "1.24.3"}
    )
    waiting = dataclasses.replace(waiting, relations=[waiting.get_relation(peer_relation.id), ready])
    result = context.run(context.on.relation_changed(ready), waiting)
    assert result.unit_status == ops.MaintenanceStatus("replanning application")


def test_refresh_stops_previous_server_while_schema_pending(context, peer_relation, admin_relation, temporal_container):
    peer_relation.local_app_data["schema_ready"] = "true"
    admin_relation.remote_app_data.update(schema_status="updating", schema_version="")
    container = dataclasses.replace(
        temporal_container,
        layers={
            "old": ops.pebble.Layer(
                {
                    "services": {
                        "temporal-server": {"override": "replace", "command": "temporal-server", "startup": "enabled"}
                    }
                }
            )
        },
        service_statuses={"temporal-server": ops.pebble.ServiceStatus.ACTIVE},
    )
    state = ops.testing.State(
        leader=True, config={"num-history-shards": 1}, relations=[peer_relation, admin_relation], containers=[container]
    )
    result = context.run(context.on.upgrade_charm(), state)
    assert result.get_container("temporal").service_statuses["temporal-server"] == ops.pebble.ServiceStatus.INACTIVE
    assert result.unit_status == ops.BlockedStatus("admin:temporal relation: schema is not ready")
