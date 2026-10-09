# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""A refreshed server waits until admin has migrated the schema for its version."""

import dataclasses

import ops
import ops.testing
import pytest


@pytest.fixture
def server_state(peer_relation, admin_relation, temporal_container, network):
    return lambda leader: ops.testing.State(
        leader=leader,
        config={"num-history-shards": 1},
        relations=[peer_relation, admin_relation],
        containers=[temporal_container],
        networks=[network],
    )


@pytest.mark.parametrize("leader", [True, False])
@pytest.mark.parametrize(
    "status,version", [("ready", "1.23.1"), ("ready", ""), ("migrating", "1.29.7"), ("failed", "")]
)
def test_pending_schema_waits_and_does_not_start_server(
    server_state, admin_relation, temporal_container, context, leader, status, version
):
    admin_relation.remote_app_data.update(schema_status=status, migrated_workload_version=version)
    result = context.run(context.on.pebble_ready(temporal_container), server_state(leader))
    assert result.unit_status == ops.WaitingStatus("admin:temporal relation: schema is pending migration")
    assert not result.get_container("temporal").plan.services


@pytest.mark.parametrize("leader", [True, False])
def test_waiting_unit_resumes_when_admin_publishes(server_state, admin_relation, temporal_container, context, leader):
    admin_relation.remote_app_data.update(schema_status="migrating", migrated_workload_version="")
    waiting = context.run(context.on.pebble_ready(temporal_container), server_state(leader))
    ready = dataclasses.replace(
        waiting.get_relation(admin_relation.id),
        remote_app_data={"schema_status": "ready", "migrated_workload_version": "1.29.7"},
    )
    relations = [ready if r.endpoint == "admin" else r for r in waiting.relations]
    result = context.run(context.on.relation_changed(ready), dataclasses.replace(waiting, relations=relations))
    assert result.unit_status == ops.MaintenanceStatus("replanning application")
