# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Scenario tests for the reconciler: every event converges on the same, idempotent, flow."""

import dataclasses
import json
import logging
import unittest.mock

import ops
import ops.testing
import pytest
from botocore.exceptions import (
    ClientError,
    ConnectTimeoutError,
    EndpointConnectionError,
    ReadTimeoutError,
)

from literals import WORKLOAD_VERSION

SENTINEL_STATUS = ops.ActiveStatus("sentinel")


@pytest.fixture
def relations(peer_relation, admin_relation, db_relation, visibility_relation, s3_relation, openfga_relation):
    return [peer_relation, admin_relation, db_relation, visibility_relation, s3_relation, openfga_relation]


@pytest.fixture
def server_state(relations, temporal_container, network, openfga_secret):
    """Return a builder of the state of a unit with all the relations the workload needs."""

    def build(leader, **overrides):
        """Build the state.

        Args:
            leader: Whether the unit is the leader.
            overrides: The fields of the state to change.

        Returns:
            The state of the unit.
        """
        kwargs = {
            "leader": leader,
            "containers": [temporal_container],
            "config": {"num-history-shards": 1},
            "relations": relations,
            "networks": [network],
            "secrets": [openfga_secret],
        }
        kwargs.update(overrides)
        return ops.testing.State(**kwargs)

    return build


@pytest.fixture
def bring_up(context, temporal_container, temporal_container_initialized):
    """Return a function that takes a state to the point where the server was planned."""

    def run(state):
        """Plan the server.

        Args:
            state: The state of the unit.

        Returns:
            The state once the server was planned.
        """
        state_out = context.run(context.on.pebble_ready(temporal_container), state)
        state_out = dataclasses.replace(state_out, containers=[temporal_container_initialized])
        admin = state_out.get_relations("admin")[0]
        return context.run(context.on.relation_changed(admin), state_out)

    return run


def _replace_relation(state, relation, **changes):
    """Return the state with the relation, looked up by ID, replaced with a modified copy.

    Args:
        state: The state holding the relation.
        relation: The relation to change.
        changes: The fields to change.

    Returns:
        The state with the changed relation.
    """
    changed = dataclasses.replace(state.get_relation(relation.id), **changes)
    return dataclasses.replace(state, relations=[changed if rel.id == relation.id else rel for rel in state.relations])


def _peer(state):
    """Return the peer application data, decoded.

    Args:
        state: The state holding the peer relation.

    Returns:
        The decoded peer application data.
    """
    return {key: json.loads(value) for key, value in state.get_relations("peer")[0].local_app_data.items()}


def _environment(state):
    """Return the environment of the temporal-server service.

    Args:
        state: The state holding the container.

    Returns:
        The environment of the service.
    """
    return state.get_container("temporal").plan.services["temporal-server"].environment


def _with_peer_data(state, **peer_data):
    """Return the state with the given keys written to the peer application data, JSON encoded.

    Args:
        state: The state holding the peer relation.
        peer_data: The keys to write; a None value removes the key.

    Returns:
        The state with the peer application data changed.
    """
    peer = state.get_relations("peer")[0]
    data = {**peer.local_app_data}
    for key, value in peer_data.items():
        if value is None:
            data.pop(key, None)
        else:
            data[key] = json.dumps(value)
    return _replace_relation(state, peer, local_app_data=data)


def _as_non_leader(state, **overrides):
    """Return the state as seen by a non leader unit of the same application.

    Args:
        state: The state of the leader.
        overrides: The fields to change.

    Returns:
        The state of a non leader unit.
    """
    return dataclasses.replace(state, leader=False, **overrides)


# Idempotency


@pytest.mark.parametrize("leader", [True, False], ids=["leader", "not leader"])
@pytest.mark.parametrize("event_name", ["config_changed", "pebble_ready", "admin_changed", "update_status"])
def test_second_identical_event_does_not_replan(
    context, server_state, bring_up, configured_container, temporal_container, leader, event_name
):
    state_out = bring_up(server_state(leader))
    plan = state_out.get_container("temporal").plan.to_dict()
    running = configured_container(state_out, ops.pebble.ServiceStatus.ACTIVE)
    state_out = dataclasses.replace(state_out, containers=[running])
    events = {
        "config_changed": context.on.config_changed(),
        "pebble_ready": context.on.pebble_ready(running),
        "admin_changed": context.on.relation_changed(state_out.get_relations("admin")[0]),
        "update_status": context.on.update_status(),
    }

    with unittest.mock.patch.object(ops.model.Container, "replan") as replan:
        state_again = context.run(events[event_name], state_out)

    replan.assert_not_called()
    assert state_again.get_container("temporal").plan.to_dict() == plan
    assert state_again.get_container("temporal").layers == running.layers


@pytest.mark.parametrize("leader", [True, False], ids=["leader", "not leader"])
def test_events_leave_the_peer_data_as_it_is_once_settled(
    context, server_state, bring_up, temporal_container_initialized, leader
):
    state_out = bring_up(server_state(True))
    peer = state_out.get_relations("peer")[0].local_app_data
    state_out = dataclasses.replace(state_out, leader=leader, containers=[temporal_container_initialized])

    state_again = context.run(context.on.config_changed(), state_out)

    assert state_again.get_relations("peer")[0].local_app_data == peer


@pytest.mark.parametrize("leader", [True, False], ids=["leader", "not leader"])
def test_config_changed_ends_replanning(
    context, server_state, bring_up, configured_container, temporal_container_initialized, leader
):
    state_out = bring_up(server_state(leader))
    state_out = dataclasses.replace(
        state_out, config={"num-history-shards": 1, "log-level": "debug"}, containers=[temporal_container_initialized]
    )

    state_final = context.run(context.on.config_changed(), state_out)

    assert state_final.unit_status == ops.MaintenanceStatus("replanning application")
    assert _environment(state_final)["LOG_LEVEL"] == "debug"
    assert state_final.get_container("temporal").service_statuses["temporal-server"] == ops.pebble.ServiceStatus.ACTIVE


# update-status


@pytest.mark.parametrize("leader", [True, False], ids=["leader", "not leader"])
def test_update_status_active_when_server_is_up(context, server_state, bring_up, configured_container, leader):
    state_out = bring_up(server_state(leader))
    running = configured_container(state_out, ops.pebble.ServiceStatus.ACTIVE)
    state_out = dataclasses.replace(state_out, containers=[running])

    with unittest.mock.patch.object(ops.model.Container, "replan") as replan:
        state_final = context.run(context.on.update_status(), state_out)

    replan.assert_not_called()
    assert state_final.unit_status == ops.ActiveStatus()
    assert state_final.workload_version == WORKLOAD_VERSION


def test_update_status_down_does_not_report_the_workload_version(context, server_state, bring_up, configured_container):
    state_out = bring_up(server_state(True))
    down = configured_container(state_out, ops.pebble.ServiceStatus.ACTIVE, check_status=ops.pebble.CheckStatus.DOWN)
    state_out = dataclasses.replace(state_out, containers=[down])

    state_final = context.run(context.on.update_status(), state_out)

    assert state_final.unit_status == ops.MaintenanceStatus("Status check: DOWN")
    assert state_final.workload_version == ""


def test_ui_relation_follows_the_server_status(
    context, server_state, bring_up, configured_container, temporal_container_initialized
):
    ui_relation = ops.testing.Relation("ui")
    state = server_state(True)
    state = dataclasses.replace(state, relations=[*state.relations, ui_relation])
    brought_up = bring_up(state)
    state_out = dataclasses.replace(brought_up, containers=[temporal_container_initialized])
    ui = state_out.get_relation(ui_relation.id)

    # The server was planned but is not known to be up yet.
    blocked = context.run(context.on.relation_changed(ui), state_out)
    assert blocked.get_relation(ui_relation.id).local_app_data["server_status"] == "blocked"

    running = configured_container(brought_up, ops.pebble.ServiceStatus.ACTIVE)
    state_out = dataclasses.replace(blocked, containers=[running])
    state_out = context.run(context.on.update_status(), state_out)
    assert state_out.unit_status == ops.ActiveStatus()
    assert state_out.get_relation(ui_relation.id).local_app_data["server_status"] == "ready"

    state_out = dataclasses.replace(state_out, unit_status=ops.ActiveStatus("auth enabled"), containers=[running])
    state_out = context.run(context.on.relation_changed(state_out.get_relation(ui_relation.id)), state_out)
    assert state_out.get_relation(ui_relation.id).local_app_data["server_status"] == "ready"


def test_admin_relation_gets_the_database_connections_from_the_leader(context, server_state):
    state = server_state(True)
    admin = state.get_relations("admin")[0]

    state_out = context.run(context.on.relation_joined(admin), state)

    assert json.loads(state_out.get_relations("admin")[0].local_app_data["database_connections"]) == {
        "db": {
            "dbname": "temporal-k8s_db",
            "host": "myhost",
            "password": "inner-light",
            "port": "5432",
            "tls": False,
            "user": "jean-luc@db",
        },
        "visibility": {
            "dbname": "temporal-k8s_visibility",
            "host": "myhost",
            "password": "inner-light",
            "port": "5432",
            "tls": False,
            "user": "jean-luc@visibility",
        },
    }


def test_admin_relation_gets_no_database_connections_from_a_non_leader(context, server_state):
    state = server_state(False)
    admin = state.get_relations("admin")[0]

    state_out = context.run(context.on.relation_joined(admin), state)

    assert not state_out.get_relations("admin")[0].local_app_data


def test_admin_relation_is_not_given_unavailable_database_connections(context, server_state, db_relation):
    state = server_state(True)
    admin = state.get_relations("admin")[0]
    state = dataclasses.replace(state, relations=[rel for rel in state.relations if rel.endpoint != "db"])

    state_out = context.run(context.on.relation_joined(admin), state)

    assert not state_out.get_relations("admin")[0].local_app_data


# Pebble


@pytest.mark.parametrize(
    "event_name, status",
    [
        ("config_changed", ops.WaitingStatus("configuring temporal")),
        ("admin_changed", ops.WaitingStatus("handling schema ready change")),
        ("update_status", SENTINEL_STATUS),
    ],
)
@pytest.mark.parametrize("leader", [True, False], ids=["leader", "not leader"])
def test_pebble_unreachable_leaves_the_status_as_announced(context, server_state, leader, event_name, status):
    state = server_state(leader, containers=[ops.testing.Container("temporal", can_connect=False)])
    state = dataclasses.replace(state, unit_status=SENTINEL_STATUS)
    events = {
        "config_changed": context.on.config_changed(),
        "admin_changed": context.on.relation_changed(state.get_relations("admin")[0]),
        "update_status": context.on.update_status(),
    }

    state_out = context.run(events[event_name], state)

    assert state_out.unit_status == status
    assert not state_out.deferred


# frontend-cert-sans-dns


@pytest.mark.parametrize("leader", [True, False], ids=["leader", "not leader"])
def test_invalid_frontend_cert_sans_dns_blocks_on_config_changed(context, server_state, leader):
    config = {"num-history-shards": 1, "frontend-cert-sans-dns": "not_a_dns!"}
    state = server_state(leader, config=config)

    state_out = context.run(context.on.config_changed(), state)

    assert state_out.unit_status == ops.BlockedStatus("Invalid frontend-cert-sans-dns, please correct the value(s).")
    assert not state_out.get_container("temporal").plan.services


@pytest.mark.parametrize("event_name", ["pebble_ready", "admin_changed", "update_status"])
def test_invalid_frontend_cert_sans_dns_is_only_checked_on_config_changed(
    context, server_state, bring_up, temporal_container, temporal_container_initialized, event_name
):
    state_out = bring_up(server_state(True))
    config = {"num-history-shards": 1, "frontend-cert-sans-dns": "not_a_dns!"}
    state_out = dataclasses.replace(state_out, config=config, containers=[temporal_container_initialized])
    events = {
        "pebble_ready": context.on.pebble_ready(temporal_container_initialized),
        "admin_changed": context.on.relation_changed(state_out.get_relations("admin")[0]),
        "update_status": context.on.update_status(),
    }

    state_final = context.run(events[event_name], state_out)

    assert not isinstance(state_final.unit_status, ops.BlockedStatus)
    assert "temporal-server" in state_final.get_container("temporal").plan.services


# Non leader units


@pytest.mark.parametrize("relation_name", ["db", "visibility", "s3-parameters"])
def test_non_leader_waits_until_the_remote_units_have_joined(context, server_state, temporal_container, relation_name):
    state = server_state(False)
    relation = state.get_relations(relation_name)[0]
    state = _replace_relation(state, relation, remote_units_data={})

    state_out = context.run(context.on.pebble_ready(temporal_container), state)

    assert state_out.unit_status == ops.WaitingStatus("configuring temporal")
    assert not state_out.get_container("temporal").plan.services


def test_non_leader_waits_for_the_openfga_remote_units_only_with_auth_enabled(
    context, server_state, temporal_container
):
    state = server_state(False)
    relation = state.get_relations("openfga")[0]
    state = _replace_relation(state, relation, remote_units_data={})

    state_out = context.run(context.on.pebble_ready(temporal_container), state)
    assert state_out.unit_status == ops.MaintenanceStatus("replanning application")

    state = dataclasses.replace(state, config={"num-history-shards": 1, "auth-enabled": True})
    state_out = context.run(context.on.pebble_ready(temporal_container), state)
    assert state_out.unit_status == ops.WaitingStatus("configuring temporal")


@pytest.mark.parametrize("relation_name", ["db", "visibility", "s3-parameters"])
def test_leader_does_not_wait_for_the_remote_units(context, server_state, temporal_container, relation_name):
    state = server_state(True)
    relation = state.get_relations(relation_name)[0]
    state = _replace_relation(state, relation, remote_units_data={})

    state_out = context.run(context.on.pebble_ready(temporal_container), state)

    assert state_out.unit_status == ops.MaintenanceStatus("replanning application")


def test_non_leader_update_status_keeps_the_status_before_the_remote_units_have_joined(
    context, server_state, temporal_container
):
    state = server_state(False)
    relation = state.get_relations("db")[0]
    state = _replace_relation(state, relation, remote_units_data={})
    state = dataclasses.replace(state, unit_status=SENTINEL_STATUS)

    state_out = context.run(context.on.update_status(), state)

    assert state_out.unit_status == SENTINEL_STATUS
    assert not state_out.get_container("temporal").plan.services


@pytest.fixture
def leader_published(server_state, bring_up, temporal_container_initialized):
    """Return the state of the leader once it reconciled, holding what it published."""
    return dataclasses.replace(bring_up(server_state(True)), containers=[temporal_container_initialized])


@pytest.mark.parametrize("relation_name", ["db", "visibility", "openfga", "s3-parameters"])
def test_non_leader_ignores_the_end_of_a_relation_the_leader_still_has(
    context, leader_published, temporal_container_initialized, relation_name
):
    # The unit that is being removed loses its relations before the leader knows anything about it.
    state = _as_non_leader(leader_published, unit_status=SENTINEL_STATUS, containers=[temporal_container_initialized])
    relation = state.get_relations(relation_name)[0]

    state_out = context.run(context.on.relation_broken(relation), state)

    assert state_out.unit_status == SENTINEL_STATUS
    assert state_out.get_container("temporal").plan == state.get_container("temporal").plan
    assert state_out.get_relations("peer")[0].local_app_data == state.get_relations("peer")[0].local_app_data


@pytest.mark.parametrize(
    "relation_name, status",
    [
        ("db", ops.BlockedStatus("db:pgsql relation: no database connection available")),
        ("visibility", ops.BlockedStatus("visibility:pgsql relation: no database connection available")),
        ("openfga", ops.MaintenanceStatus("replanning application")),
        ("s3-parameters", ops.MaintenanceStatus("replanning application")),
    ],
)
def test_leader_acts_on_the_end_of_a_relation(
    context, leader_published, temporal_container_initialized, relation_name, status
):
    state = dataclasses.replace(
        leader_published, unit_status=SENTINEL_STATUS, containers=[temporal_container_initialized]
    )
    relation = state.get_relations(relation_name)[0]

    state_out = context.run(context.on.relation_broken(relation), state)

    assert state_out.unit_status == status


@pytest.mark.parametrize("relation_name", ["db", "visibility"])
def test_non_leader_follows_the_end_of_a_relation_when_no_digest_is_published(
    context, server_state, temporal_container_initialized, relation_name
):
    state = server_state(False, containers=[temporal_container_initialized])
    relation = state.get_relations(relation_name)[0]

    state_out = context.run(context.on.relation_broken(relation), state)

    assert state_out.unit_status == ops.BlockedStatus(
        f"{relation_name}:pgsql relation: no database connection available"
    )


def test_non_leader_follows_the_leader_on_peer_changes(
    context, leader_published, temporal_container, temporal_container_initialized
):
    # The leader published the digest of what it reads: this unit reads the same.
    state = _as_non_leader(leader_published, unit_status=SENTINEL_STATUS, containers=[temporal_container])
    peer = state.get_relations("peer")[0]

    state_out = context.run(context.on.relation_changed(peer), state)

    assert state_out.unit_status == ops.MaintenanceStatus("replanning application")
    assert "temporal-server" in state_out.get_container("temporal").plan.services


def test_non_leader_ignores_peer_changes_while_it_reads_other_relation_data_than_the_leader(
    context, leader_published, temporal_container
):
    state = _as_non_leader(leader_published, unit_status=SENTINEL_STATUS, containers=[temporal_container])
    state = _with_peer_data(state, relation_digest="published-by-the-leader-for-other-data")
    peer = state.get_relations("peer")[0]

    state_out = context.run(context.on.relation_changed(peer), state)

    assert state_out.unit_status == SENTINEL_STATUS
    assert not state_out.get_container("temporal").plan.services


def test_leader_ignores_peer_changes(context, leader_published, temporal_container):
    state = dataclasses.replace(leader_published, unit_status=SENTINEL_STATUS, containers=[temporal_container])
    peer = state.get_relations("peer")[0]

    state_out = context.run(context.on.relation_changed(peer), state)

    assert state_out.unit_status == SENTINEL_STATUS
    assert not state_out.get_container("temporal").plan.services


@pytest.mark.parametrize("leader", [True, False], ids=["leader", "not leader"])
@unittest.mock.patch("socket.gethostbyname", return_value="127.0.0.1")
def test_upgrade_charm_is_reconciled_by_the_leader_only(mock_dns, context, server_state, leader):
    state = dataclasses.replace(server_state(leader), unit_status=SENTINEL_STATUS)

    state_out = context.run(context.on.upgrade_charm(), state)

    assert (state_out.unit_status == SENTINEL_STATUS) is not leader


@pytest.mark.parametrize("relation_name", ["admin", "db", "visibility"])
def test_relation_events_are_ignored_until_the_peer_relation_exists(
    context, server_state, temporal_container, relation_name
):
    state = server_state(True)
    state = dataclasses.replace(
        state, relations=[rel for rel in state.relations if rel.endpoint != "peer"], unit_status=SENTINEL_STATUS
    )
    relation = state.get_relations(relation_name)[0]

    state_out = context.run(context.on.relation_changed(relation), state)

    assert state_out.unit_status == SENTINEL_STATUS


# Legacy peer data


def _database_connection(rel_name):
    """Return the connection to a database as the previous revisions persisted it."""
    return {
        "dbname": "temporal-k8s_db" if rel_name == "db" else "temporal-k8s_visibility",
        "host": "myhost",
        "port": "5432",
        "user": "jean-luc@db" if rel_name == "db" else "jean-luc@visibility",
        "password": "inner-light",
        "tls": False,
    }


def _openfga_blob(auth_model_id="123"):
    """Return the OpenFGA state as the previous revisions persisted it."""
    return {
        "store_id": "storeid12345",
        "token": "openfga_token",
        "address": "127.0.0.1",
        "port": 8080,
        "scheme": "http",
        "full_http_url": "http://127.0.0.1:8080",
        "auth_model_id": auth_model_id,
    }


S3_BLOB = {
    "bucket": "bucket_name",
    "endpoint": "s3.us-east-2.amazonaws.com",
    "region": "region",
    "aws_access_key_id": "access",
    "aws_secret_access_key": "secret",
    "uri_style": "path",
    "bucket_created": True,
}


def _old_revision_peer_data(state, **overrides):
    """Return the state with the peer data the previous revisions leave: only what they read.

    Args:
        state: The state holding the peer relation.
        overrides: The keys to write instead of the default ones.

    Returns:
        The state with the peer data of the previous revisions.
    """
    data = {
        "database_connections": {"db": _database_connection("db"), "visibility": _database_connection("visibility")},
        "s3": S3_BLOB,
        "openfga": _openfga_blob(),
        "s3_bucket": None,
    }
    data.update(overrides)
    return _with_peer_data(state, **data)


def _stale_peer_data(state):
    """Return the state with legacy peer data that no longer matches what the relations provide."""
    return _with_peer_data(
        state,
        database_connections={
            "db": {"dbname": "stale", "host": "stale-host", "port": "1", "user": "u", "password": "p", "tls": True},
            "visibility": None,
        },
        s3={**S3_BLOB, "bucket": "stale", "endpoint": "stale"},
        openfga={**_openfga_blob(), "token": "stale-token", "address": "stale", "port": 1, "full_http_url": "http://x"},
    )


@pytest.mark.parametrize("event_name", ["config_changed", "update_status", "admin_changed", "pebble_ready"])
def test_leader_leaves_the_peer_data_of_the_previous_revisions_intact(
    context, server_state, bring_up, temporal_container_initialized, temporal_container, event_name
):
    # A unit running the previous revision reads database_connections, s3 and openfga: the new
    # revision on the leader must not remove or reshape any of them.
    state = _old_revision_peer_data(server_state(True))
    state_out = bring_up(state)
    state_out = dataclasses.replace(state_out, containers=[temporal_container_initialized])
    events = {
        "config_changed": context.on.config_changed(),
        "update_status": context.on.update_status(),
        "admin_changed": context.on.relation_changed(state_out.get_relations("admin")[0]),
        "pebble_ready": context.on.pebble_ready(temporal_container),
    }

    state_final = context.run(events[event_name], state_out)

    peer = _peer(state_final)
    assert peer["database_connections"] == {
        "db": _database_connection("db"),
        "visibility": _database_connection("visibility"),
    }
    assert peer["s3"] == S3_BLOB
    assert peer["openfga"] == _openfga_blob()
    assert peer["num_history_shards"] == 1
    environment = _environment(state_final)
    assert environment["DB_HOST"] == "myhost"
    assert environment["VISIBILITY_HOST"] == "myhost"
    assert environment["SQL_TLS_ENABLED"] is False
    assert environment["ARCHIVAL_ENDPOINT"] == "s3.us-east-2.amazonaws.com"


def test_leader_writes_the_peer_data_of_the_previous_revisions_in_their_format(context, server_state):
    # The units running the previous revision follow what the new leader gets from the relations.
    state = server_state(True)
    assert not {"database_connections", "s3"} & set(_peer(state))

    state_out = context.run(context.on.config_changed(), state)

    peer = _peer(state_out)
    assert peer["database_connections"] == {
        "db": _database_connection("db"),
        "visibility": _database_connection("visibility"),
    }
    assert peer["s3"] == S3_BLOB
    assert peer["openfga"] == _openfga_blob()


def test_leader_keeps_the_peer_data_of_the_previous_revisions_up_to_date(context, server_state):
    state = _stale_peer_data(server_state(True))

    state_out = context.run(context.on.config_changed(), state)

    peer = _peer(state_out)
    assert peer["database_connections"] == {
        "db": _database_connection("db"),
        "visibility": _database_connection("visibility"),
    }
    assert peer["s3"] == S3_BLOB
    assert peer["openfga"] == _openfga_blob()
    environment = _environment(state_out)
    assert environment["DB_HOST"] == "myhost"
    assert environment["ARCHIVAL_ENDPOINT"] == "s3.us-east-2.amazonaws.com"


@pytest.mark.parametrize("rel_name", ["db", "visibility"])
def test_leader_keeps_a_database_connection_the_relation_does_not_provide_yet(
    context, server_state, relations, rel_name
):
    state = _old_revision_peer_data(server_state(True))
    relation = state.get_relations(rel_name)[0]
    state = _replace_relation(state, relation, remote_app_data={})

    state_out = context.run(context.on.config_changed(), state)

    assert _peer(state_out)["database_connections"][rel_name] == _database_connection(rel_name)
    assert state_out.unit_status == ops.BlockedStatus(f"{rel_name}:pgsql relation: no database connection available")


@pytest.mark.parametrize("rel_name", ["db", "visibility"])
def test_leader_resets_the_database_connection_when_the_relation_is_broken(context, server_state, rel_name):
    state = _old_revision_peer_data(server_state(True))
    relation = state.get_relations(rel_name)[0]
    other = "visibility" if rel_name == "db" else "db"

    state_out = context.run(context.on.relation_broken(relation), state)

    connections = _peer(state_out)["database_connections"]
    assert connections[rel_name] is None
    assert connections[other] == _database_connection(other)


def test_leader_resets_the_s3_data_when_the_credentials_are_gone(context, server_state, s3_relation):
    state = _old_revision_peer_data(server_state(True))

    state_out = context.run(context.on.relation_broken(state.get_relation(s3_relation.id)), state)

    assert _peer(state_out)["s3"] is None


def test_leader_does_not_reset_the_s3_data_while_the_credentials_are_incomplete(
    context, server_state, s3_relation, create_bucket
):
    state = _old_revision_peer_data(server_state(True))
    state = _replace_relation(state, s3_relation, remote_app_data={"bucket": "bucket_name"})

    state_out = context.run(context.on.config_changed(), state)

    assert _peer(state_out)["s3"] == S3_BLOB


def test_leader_does_not_add_the_legacy_peer_data_without_the_relations(context, server_state, s3_relation):
    state = server_state(True)
    state = dataclasses.replace(
        state, relations=[rel for rel in state.relations if rel.endpoint not in ("db", "visibility", "s3-parameters")]
    )

    state_out = context.run(context.on.config_changed(), state)

    assert not {"database_connections", "s3"} & set(_peer(state_out))


def test_non_leader_leaves_the_legacy_peer_data_alone(context, server_state, temporal_container):
    state = _stale_peer_data(server_state(False))
    peer = state.get_relations("peer")[0].local_app_data

    state_out = context.run(context.on.pebble_ready(temporal_container), state)

    assert state_out.get_relations("peer")[0].local_app_data == peer
    assert _environment(state_out)["DB_HOST"] == "myhost"


def test_non_leader_reads_the_relations_whatever_the_legacy_peer_data_holds(context, server_state, temporal_container):
    state = _with_peer_data(_stale_peer_data(server_state(False)), s3_bucket=None)

    state_out = context.run(context.on.pebble_ready(temporal_container), state)

    environment = _environment(state_out)
    assert environment["DB_HOST"] == "myhost"
    assert environment["VISIBILITY_HOST"] == "myhost"
    assert environment["SQL_TLS_ENABLED"] is False
    assert "ARCHIVAL_ENABLED" not in environment


def test_non_leader_with_a_leader_running_the_previous_revision(
    context, server_state, create_bucket, temporal_container
):
    # The previous revision's leader persists no bucket record and no digest, only what it reads.
    state = _old_revision_peer_data(server_state(False, config={"num-history-shards": 1, "auth-enabled": True}))
    assert not {"s3_bucket", "relation_digest"} & set(_peer(state))

    state_out = context.run(context.on.pebble_ready(temporal_container), state)

    create_bucket.assert_not_called()
    assert state_out.unit_status == ops.MaintenanceStatus("replanning application")
    environment = _environment(state_out)
    assert environment["DB_HOST"] == "myhost"
    assert environment["ARCHIVAL_ENABLED"] is True
    assert environment["OFGA_AUTH_MODEL_ID"] == "123"
    assert environment["OFGA_API_PORT"] == 8080
    assert state_out.get_relations("peer")[0].local_app_data == state.get_relations("peer")[0].local_app_data


def test_non_leader_blocks_on_the_bucket_failure_the_previous_revision_persisted(
    context, server_state, temporal_container
):
    state = _old_revision_peer_data(server_state(False), s3={**S3_BLOB, "bucket_created": False})

    state_out = context.run(context.on.pebble_ready(temporal_container), state)

    assert state_out.unit_status == ops.BlockedStatus("s3:archival failed to create s3 bucket.")


def test_non_leader_does_not_use_the_credentials_the_previous_revision_did_not_persist(
    context, server_state, temporal_container
):
    state = _old_revision_peer_data(server_state(False), s3={**S3_BLOB, "bucket": "another-bucket"})

    state_out = context.run(context.on.pebble_ready(temporal_container), state)

    assert "ARCHIVAL_ENABLED" not in _environment(state_out)


def test_the_new_keys_are_not_read_by_the_previous_revision(context, server_state):
    # The previous revision reads only these keys; the new one adds `s3_bucket`, `relation_digest`.
    state = _old_revision_peer_data(server_state(True))

    state_out = context.run(context.on.config_changed(), state)

    legacy_keys = {"database_connections", "s3", "openfga", "num_history_shards"}
    assert set(_peer(state_out)) == legacy_keys | {"s3_bucket", "relation_digest"}


def test_leader_drops_the_openfga_data_when_the_relation_is_broken(context, server_state):
    state = server_state(True)
    openfga = state.get_relations("openfga")[0]
    assert "openfga" in _peer(state)

    state_out = context.run(context.on.relation_broken(openfga), state)

    assert "openfga" not in _peer(state_out)


# OpenFGA authorization model


def test_store_created_resets_the_authorization_model(context, server_state):
    state = server_state(True, config={"num-history-shards": 1, "auth-enabled": True})
    openfga = state.get_relations("openfga")[0]
    assert _peer(state)["openfga"]["auth_model_id"] == "123"

    state_out = context.run(context.on.relation_changed(openfga), state)

    assert _peer(state_out)["openfga"] == _openfga_blob(auth_model_id=None)
    assert state_out.unit_status == ops.BlockedStatus("missing openfga authorization model")


def test_authorization_model_is_kept_while_the_store_is_not_delivered_again(context, server_state):
    state = server_state(True, config={"num-history-shards": 1, "auth-enabled": True})

    state_out = context.run(context.on.config_changed(), state)

    assert _peer(state_out)["openfga"] == _openfga_blob()
    assert state_out.unit_status == ops.MaintenanceStatus("replanning application")
    assert _environment(state_out)["OFGA_AUTH_MODEL_ID"] == "123"


def test_authorization_model_of_another_store_is_not_used(context, server_state):
    state = server_state(True, config={"num-history-shards": 1, "auth-enabled": True})
    state = _with_peer_data(state, openfga={"store_id": "another-store", "auth_model_id": "123"})

    state_out = context.run(context.on.config_changed(), state)

    assert state_out.unit_status == ops.BlockedStatus("missing openfga authorization model")
    assert not state_out.get_container("temporal").plan.services
    # The persisted state follows the store the relation provides, which has no model yet.
    assert _peer(state_out)["openfga"] == _openfga_blob(auth_model_id=None)


def test_authorization_model_is_persisted_with_the_other_fields_left_as_they_are(context, server_state):
    state = server_state(True, config={"num-history-shards": 1, "auth-enabled": True})

    with context(context.on.config_changed(), state) as manager:
        manager.run()
        manager.charm._peer_set("openfga", {**_openfga_blob(), "extra": "kept"})
        manager.charm._store_openfga_auth_model_id("storeid12345", "456")
        persisted = manager.charm._peer_get("openfga")

    assert persisted == {**_openfga_blob(auth_model_id="456"), "extra": "kept"}


# OpenFGA state that is present but unusable


def _openfga_without_store_info(state):
    """Return the state with the OpenFGA relation not providing any store info."""
    return _replace_relation(state, state.get_relations("openfga")[0], remote_app_data={})


def _openfga_with_invalid_url(state):
    """Return the state with the OpenFGA relation providing a store with an invalid URL."""
    relation = state.get_relations("openfga")[0]
    data = {**relation.remote_app_data, "http_api_url": "https://openfga.example.com?foo=bar"}
    return _replace_relation(state, relation, remote_app_data=data)


@pytest.mark.parametrize("unusable", [_openfga_without_store_info, _openfga_with_invalid_url])
@pytest.mark.parametrize("event_name", ["config_changed", "pebble_ready"])
def test_openfga_state_that_is_complete_keeps_working_while_the_relation_gives_no_usable_store(
    context, server_state, temporal_container, unusable, event_name
):
    state = unusable(server_state(True, config={"num-history-shards": 1, "auth-enabled": True}))
    state = _with_peer_data(state, openfga=_openfga_blob("456"))
    events = {
        "config_changed": context.on.config_changed(),
        "pebble_ready": context.on.pebble_ready(temporal_container),
    }

    state_out = context.run(events[event_name], state)

    assert _peer(state_out)["openfga"] == _openfga_blob("456")
    assert state_out.unit_status == ops.MaintenanceStatus("replanning application")
    environment = _environment(state_out)
    assert environment["OFGA_API_HOST"] == "127.0.0.1"
    assert environment["OFGA_AUTH_MODEL_ID"] == "456"


@pytest.mark.parametrize("unusable", [_openfga_without_store_info, _openfga_with_invalid_url])
@pytest.mark.parametrize(
    "missing, message",
    [
        (["full_http_url"], "openfga:missing parameters ['full_http_url']"),
        (["port", "full_http_url"], "openfga:missing parameters ['port', 'full_http_url']"),
        (["token"], "openfga:missing parameters ['token']"),
    ],
)
@pytest.mark.parametrize("leader", [True, False], ids=["leader", "not leader"])
def test_openfga_state_that_lacks_parameters_is_reported_while_the_relation_gives_no_usable_store(
    context, server_state, temporal_container, unusable, missing, message, leader
):
    state = unusable(server_state(leader, config={"num-history-shards": 1, "auth-enabled": True}))
    blob = {key: value for key, value in _openfga_blob().items() if key not in missing}
    state = _with_peer_data(state, openfga=blob)

    state_out = context.run(context.on.pebble_ready(temporal_container), state)

    assert state_out.unit_status == ops.BlockedStatus(message)
    assert _peer(state_out)["openfga"] == blob


def test_missing_openfga_authorization_model_is_reported_while_the_relation_gives_no_usable_store(
    context, server_state, temporal_container
):
    state = _openfga_without_store_info(server_state(True, config={"num-history-shards": 1, "auth-enabled": True}))
    state = _with_peer_data(state, openfga=_openfga_blob(None))

    state_out = context.run(context.on.pebble_ready(temporal_container), state)

    assert state_out.unit_status == ops.BlockedStatus("missing openfga authorization model")


@pytest.mark.parametrize("unusable", [_openfga_without_store_info, _openfga_with_invalid_url])
def test_openfga_relation_is_not_ready_without_a_usable_store_or_a_persisted_state(
    context, server_state, temporal_container, unusable
):
    state = unusable(server_state(True, config={"num-history-shards": 1, "auth-enabled": True}))
    state = _with_peer_data(state, openfga=None)

    state_out = context.run(context.on.pebble_ready(temporal_container), state)

    assert state_out.unit_status == ops.BlockedStatus("openfga:temporal relation not ready")
    assert "openfga" not in _peer(state_out)


def test_invalid_url_on_store_created_leaves_the_persisted_state_working(context, server_state):
    state = _openfga_with_invalid_url(server_state(True, config={"num-history-shards": 1, "auth-enabled": True}))
    state = _with_peer_data(state, openfga=_openfga_blob("456"))
    openfga = state.get_relations("openfga")[0]

    state_out = context.run(context.on.relation_changed(openfga), state)

    assert _peer(state_out)["openfga"] == _openfga_blob("456")
    assert state_out.unit_status == ops.MaintenanceStatus("replanning application")
    environment = _environment(state_out)
    assert environment["OFGA_AUTH_MODEL_ID"] == "456"
    assert environment["OFGA_API_HOST"] == "127.0.0.1"


def test_store_info_that_is_not_there_on_store_created_leaves_the_persisted_state_alone(context, server_state):
    state = _openfga_without_store_info(server_state(True, config={"num-history-shards": 1, "auth-enabled": True}))
    openfga = state.get_relations("openfga")[0]

    state_out = context.run(context.on.relation_changed(openfga), state)

    assert _peer(state_out)["openfga"] == _peer(state)["openfga"]


def test_non_leader_uses_the_authorization_model_the_leader_persisted(context, server_state, temporal_container):
    state = server_state(False, config={"num-history-shards": 1, "auth-enabled": True})

    state_out = context.run(context.on.pebble_ready(temporal_container), state)

    assert state_out.unit_status == ops.MaintenanceStatus("replanning application")
    environment = _environment(state_out)
    assert environment["OFGA_AUTH_MODEL_ID"] == "123"
    assert environment["OFGA_STORE_ID"] == "storeid12345"
    assert environment["OFGA_SECRETS_BEARER_TOKEN"] == "openfga_token"


def test_non_leader_does_not_use_the_authorization_model_of_another_store(context, server_state, temporal_container):
    state = server_state(False, config={"num-history-shards": 1, "auth-enabled": True})
    state = _with_peer_data(state, openfga={"store_id": "another-store", "auth_model_id": "123"})

    state_out = context.run(context.on.pebble_ready(temporal_container), state)

    assert state_out.unit_status == ops.BlockedStatus("missing openfga authorization model")


# Relation digest


def test_leader_publishes_the_relation_digest(context, leader_published):
    digest = _peer(leader_published)["relation_digest"]

    assert isinstance(digest, str)
    assert len(digest) == 64


def test_relation_digest_follows_the_relation_data(context, leader_published, db_relation, postgres_db_data):
    digest = _peer(leader_published)["relation_digest"]
    state = _replace_relation(
        leader_published,
        db_relation,
        remote_app_data={**postgres_db_data, "endpoints": "otherhost:5432"},
    )

    state_out = context.run(context.on.config_changed(), state)

    assert _peer(state_out)["relation_digest"] != digest
    assert _environment(state_out)["DB_HOST"] == "otherhost"


def test_relation_digest_is_stable_for_unchanged_relation_data(context, leader_published):
    digest = _peer(leader_published)["relation_digest"]

    state_out = context.run(context.on.config_changed(), leader_published)

    assert _peer(state_out)["relation_digest"] == digest


def test_relation_digest_ignores_the_configuration(context, leader_published):
    digest = _peer(leader_published)["relation_digest"]
    state = dataclasses.replace(leader_published, config={"num-history-shards": 1, "log-level": "debug"})

    state_out = context.run(context.on.config_changed(), state)

    assert _peer(state_out)["relation_digest"] == digest


def test_non_leader_does_not_publish_the_relation_digest(context, server_state, temporal_container):
    state = server_state(False)

    state_out = context.run(context.on.pebble_ready(temporal_container), state)

    assert "relation_digest" not in _peer(state_out)


# S3 archival


def _without_bucket_record(state):
    """Return the state without the outcome of the bucket creation in the peer data.

    Args:
        state: The state holding the peer relation.

    Returns:
        The state without the record.
    """
    return _with_peer_data(state, s3_bucket=None)


def test_bucket_is_created_when_the_credentials_change(
    context, server_state, create_bucket, s3_relation, s3_bucket_fingerprint
):
    state = _without_bucket_record(server_state(True))

    state_out = context.run(context.on.relation_changed(state.get_relation(s3_relation.id)), state)

    create_bucket.assert_called_once()
    s3_parameters, endpoint = create_bucket.call_args.args
    assert s3_parameters["bucket"] == "bucket_name"
    assert endpoint == "s3.us-east-2.amazonaws.com"
    assert _peer(state_out)["s3_bucket"] == {"fingerprint": s3_bucket_fingerprint, "bucket_created": True}
    environment = _environment(state_out)
    assert environment["ARCHIVAL_ENABLED"] is True
    assert environment["ARCHIVAL_BUCKET_REGION"] == "region"
    assert environment["AWS_ACCESS_KEY_ID"] == "access"


def test_bucket_creation_failure_blocks_until_the_credentials_change_again(
    context, server_state, create_bucket, s3_relation, s3_bucket_fingerprint
):
    state = _without_bucket_record(server_state(True))
    s3 = state.get_relation(s3_relation.id)
    create_bucket.side_effect = ClientError({"Error": {"Code": "AccessDenied"}}, "CreateBucket")

    state_out = context.run(context.on.relation_changed(s3), state)

    assert _peer(state_out)["s3_bucket"] == {"fingerprint": s3_bucket_fingerprint, "bucket_created": False}
    assert state_out.unit_status == ops.BlockedStatus("s3:archival failed to create s3 bucket.")
    assert not state_out.get_container("temporal").plan.services

    # The other events don't retry...
    create_bucket.reset_mock()
    state_out = context.run(context.on.config_changed(), state_out)
    create_bucket.assert_not_called()
    assert state_out.unit_status == ops.BlockedStatus("s3:archival failed to create s3 bucket.")

    # ...but new credentials do.
    create_bucket.side_effect = None
    state_out = context.run(context.on.relation_changed(state_out.get_relation(s3_relation.id)), state_out)
    create_bucket.assert_called_once()
    assert _peer(state_out)["s3_bucket"] == {"fingerprint": s3_bucket_fingerprint, "bucket_created": True}
    assert state_out.unit_status == ops.MaintenanceStatus("replanning application")


def test_bucket_creation_error_blocks(context, server_state, create_bucket, s3_relation):
    state = _without_bucket_record(server_state(True))
    create_bucket.side_effect = ValueError("no session")

    state_out = context.run(context.on.relation_changed(state.get_relation(s3_relation.id)), state)

    assert state_out.unit_status == ops.BlockedStatus("s3:archival failed to create s3 bucket.")


NETWORK_ERRORS = [
    EndpointConnectionError(endpoint_url="https://s3.example.com"),
    ConnectTimeoutError(endpoint_url="https://s3.example.com"),
    ReadTimeoutError(endpoint_url="https://s3.example.com"),
    ConnectionError("connection refused"),
    RuntimeError("unexpected"),
]


@pytest.mark.parametrize("error", NETWORK_ERRORS, ids=lambda error: type(error).__name__)
@pytest.mark.parametrize("event_name", ["relation_changed", "config_changed", "update_status", "pebble_ready"])
def test_bucket_network_failure_does_not_crash_the_hook(
    context,
    server_state,
    create_bucket,
    s3_relation,
    s3_bucket_fingerprint,
    temporal_container,
    error,
    event_name,
    caplog,
):
    state = _without_bucket_record(server_state(True))
    create_bucket.side_effect = error
    events = {
        "relation_changed": context.on.relation_changed(state.get_relation(s3_relation.id)),
        "config_changed": context.on.config_changed(),
        "update_status": context.on.update_status(),
        "pebble_ready": context.on.pebble_ready(temporal_container),
    }

    with caplog.at_level(logging.WARNING):
        state_out = context.run(events[event_name], state)

    create_bucket.assert_called_once()
    assert _peer(state_out)["s3_bucket"] == {"fingerprint": s3_bucket_fingerprint, "bucket_created": False}
    assert "failed to create the S3 bucket bucket_name" in caplog.text
    if event_name != "update_status":
        # update-status never reports what the other events do.
        assert state_out.unit_status == ops.BlockedStatus("s3:archival failed to create s3 bucket.")
        assert not state_out.get_container("temporal").plan.services


@pytest.mark.parametrize("error", NETWORK_ERRORS, ids=lambda error: type(error).__name__)
def test_bucket_network_failure_is_not_retried_on_every_event(
    context, server_state, create_bucket, s3_relation, s3_bucket_fingerprint, error
):
    state = _without_bucket_record(server_state(True))
    create_bucket.side_effect = error
    state_out = context.run(context.on.relation_changed(state.get_relation(s3_relation.id)), state)
    create_bucket.reset_mock()

    for event in (context.on.update_status(), context.on.config_changed(), context.on.update_status()):
        state_out = context.run(event, state_out)

    create_bucket.assert_not_called()
    assert state_out.unit_status == ops.BlockedStatus("s3:archival failed to create s3 bucket.")

    # New credentials are tried again.
    create_bucket.side_effect = None
    state_out = context.run(context.on.relation_changed(state_out.get_relation(s3_relation.id)), state_out)
    create_bucket.assert_called_once()
    assert _peer(state_out)["s3_bucket"] == {"fingerprint": s3_bucket_fingerprint, "bucket_created": True}
    assert state_out.unit_status == ops.MaintenanceStatus("replanning application")


def test_bucket_network_failure_is_tried_again_when_the_relation_data_changes(
    context, server_state, create_bucket, s3_relation, s3_config, s3_bucket_fingerprint
):
    state = server_state(True)
    state = _replace_relation(state, s3_relation, remote_app_data={**s3_config, "bucket": "another-bucket"})
    create_bucket.side_effect = EndpointConnectionError(endpoint_url="https://s3.example.com")

    state_out = context.run(context.on.update_status(), state)

    create_bucket.assert_called_once()
    record = _peer(state_out)["s3_bucket"]
    assert record["bucket_created"] is False
    assert record["fingerprint"] != s3_bucket_fingerprint
    # The units still running the previous revision are told the same.
    assert _peer(state_out)["s3"]["bucket_created"] is False


def test_bucket_is_not_created_again_for_the_same_credentials(context, server_state, create_bucket):
    state = server_state(True)

    state_out = context.run(context.on.config_changed(), state)

    create_bucket.assert_not_called()
    assert _environment(state_out)["ARCHIVAL_ENABLED"] is True


def test_bucket_is_created_for_new_credentials_on_any_event(
    context, server_state, create_bucket, s3_relation, s3_config, s3_bucket_fingerprint
):
    state = server_state(True)
    state = _replace_relation(state, s3_relation, remote_app_data={**s3_config, "bucket": "another-bucket"})

    state_out = context.run(context.on.config_changed(), state)

    create_bucket.assert_called_once()
    record = _peer(state_out)["s3_bucket"]
    assert record["bucket_created"] is True
    assert record["fingerprint"] != s3_bucket_fingerprint


def test_bucket_record_is_dropped_with_the_relation(context, server_state, s3_relation):
    state = server_state(True)

    state_out = context.run(context.on.relation_broken(state.get_relation(s3_relation.id)), state)

    assert "s3_bucket" not in _peer(state_out)
    assert "ARCHIVAL_ENABLED" not in _environment(state_out)
    assert state_out.unit_status == ops.MaintenanceStatus("replanning application")


def test_non_leader_uses_the_bucket_outcome_the_leader_recorded(
    context, server_state, create_bucket, temporal_container
):
    state = server_state(False)

    state_out = context.run(context.on.pebble_ready(temporal_container), state)

    create_bucket.assert_not_called()
    assert _environment(state_out)["ARCHIVAL_ENABLED"] is True


def test_non_leader_blocks_on_the_bucket_failure_the_leader_recorded(
    context, server_state, temporal_container, s3_bucket_fingerprint
):
    state = _with_peer_data(
        server_state(False), s3_bucket={"fingerprint": s3_bucket_fingerprint, "bucket_created": False}
    )

    state_out = context.run(context.on.pebble_ready(temporal_container), state)

    assert state_out.unit_status == ops.BlockedStatus("s3:archival failed to create s3 bucket.")


def test_non_leader_does_not_use_the_credentials_the_leader_has_not_processed(
    context, server_state, create_bucket, temporal_container
):
    state = _without_bucket_record(server_state(False))

    state_out = context.run(context.on.pebble_ready(temporal_container), state)

    create_bucket.assert_not_called()
    assert "ARCHIVAL_ENABLED" not in _environment(state_out)


# Logs


def test_incomplete_s3_credentials_are_ignored(context, server_state, create_bucket, s3_relation, caplog):
    state = _without_bucket_record(server_state(True))
    state = _replace_relation(state, s3_relation, remote_app_data={"bucket": "bucket_name"})

    with caplog.at_level(logging.WARNING):
        state_out = context.run(context.on.config_changed(), state)

    create_bucket.assert_not_called()
    assert "Missing required S3 parameters" in caplog.text
    assert "ARCHIVAL_ENABLED" not in _environment(state_out)
