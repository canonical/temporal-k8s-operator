# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
#
# Learn more about testing at: https://juju.is/docs/sdk/testing


"""Temporal charm unit tests."""

# pylint:disable=protected-access

import json
from unittest import TestCase

from ops.model import ActiveStatus, BlockedStatus
from ops.testing import Harness

from charm import TemporalK8SCharm
from state import State

SERVER_PORT = "7233"


class TestCharm(TestCase):
    """Unit tests.

    Attrs:
        maxDiff: Specifies max difference shown by failed tests.
    """

    maxDiff = None

    def setUp(self):
        """Set up for the unit tests."""
        self.harness = Harness(TemporalK8SCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.set_can_connect("temporal", True)
        self.harness.set_leader(True)
        self.harness.set_model_name("temporal-model")
        self.harness.begin()

    def test_initial_plan(self):
        """The initial pebble plan is empty."""
        harness = self.harness
        initial_plan = harness.get_container_pebble_plan("temporal").to_dict()
        self.assertEqual(initial_plan, {})

    def test_blocked_by_peer_relation_not_ready(self):
        """The charm is blocked without a peer relation."""
        harness = self.harness

        # Simulate pebble readiness.
        container = harness.model.unit.get_container("temporal")
        harness.charm.on.temporal_pebble_ready.emit(container)

        # No plans are set yet.
        got_plan = harness.get_container_pebble_plan("temporal").to_dict()
        self.assertEqual(got_plan, {})

        # The BlockStatus is set with a message.
        self.assertEqual(harness.model.unit.status, BlockedStatus("peer relation not ready"))

    def test_blocked_by_db(self):
        """The charm is blocked without a db:pgsql relation with a ready master."""
        harness = self.harness

        # Simulate peer relation readiness.
        self.harness.add_relation("peer", "temporal")

        # Simulate pebble readiness.
        container = harness.model.unit.get_container("temporal")
        harness.charm.on.temporal_pebble_ready.emit(container)

        # No plans are set yet.
        got_plan = harness.get_container_pebble_plan("temporal").to_dict()
        self.assertEqual(got_plan, {})

        # The BlockStatus is set with a message.
        self.assertEqual(
            harness.model.unit.status,
            BlockedStatus("database relation not ready"),
        )

    def test_blocked_by_visibility(self):
        """The charm is blocked without a visibility:pgsql relation with a ready master."""
        harness = self.harness

        # Simulate peer relation readiness.
        self.harness.add_relation("peer", "temporal")

        # Simulate pebble readiness.
        container = harness.model.unit.get_container("temporal")
        harness.charm.on.temporal_pebble_ready.emit(container)

        # Simulate db readiness.
        event = make_database_changed_event("db")
        harness.charm._on_database_changed(event)

        # No plans are set yet.
        got_plan = harness.get_container_pebble_plan("temporal").to_dict()
        self.assertEqual(got_plan, {})

        # The BlockStatus is set with a message.
        self.assertEqual(
            harness.model.unit.status,
            BlockedStatus("visibility:pgsql relation: no database connection available"),
        )

    def test_blocked_by_schema_not_ready(self):
        """The charm is blocked without a admin:temporal relation with a ready schema."""
        harness = self.harness

        # Simulate peer relation readiness.
        self.harness.add_relation("peer", "temporal")

        # Simulate pebble readiness.
        container = harness.model.unit.get_container("temporal")
        harness.charm.on.temporal_pebble_ready.emit(container)

        # Simulate db readiness.
        event = make_database_changed_event("db")
        harness.charm._on_database_changed(event)

        # Simulate visibility readiness.
        event = make_database_changed_event("visibility")
        harness.charm._on_database_changed(event)

        # No plans are set yet.
        got_plan = harness.get_container_pebble_plan("temporal").to_dict()
        self.assertEqual(got_plan, {})

        # The BlockStatus is set with a message.
        self.assertEqual(harness.model.unit.status, BlockedStatus("admin:temporal relation: schema is not ready"))

    def test_ready(self):
        """The pebble plan is correctly generated when the charm is ready."""
        harness = self.harness
        simulate_lifecycle(harness)

        # The plan is generated after pebble is ready.
        want_plan = {
            "services": {
                "temporal": {
                    "summary": "temporal server",
                    "command": "temporal-server --env charm start "
                    "--service=frontend --service=history --service=matching --service=worker",
                    "startup": "enabled",
                    "override": "replace",
                    "environment": {
                        "DB_HOST": "myhost",
                        "DB_NAME": "temporal-k8s_db",
                        "DB_PORT": "5432",
                        "DB_PSWD": "inner-light",
                        "DB_USER": "jean-luc@db",
                        "VISIBILITY_HOST": "myhost",
                        "VISIBILITY_NAME": "temporal-k8s_visibility",
                        "VISIBILITY_PORT": "5432",
                        "VISIBILITY_PSWD": "inner-light",
                        "VISIBILITY_USER": "jean-luc@visibility",
                        "LOG_LEVEL": "info",
                    },
                }
            },
        }
        got_plan = harness.get_container_pebble_plan("temporal").to_dict()
        self.assertEqual(got_plan, want_plan)

        # The service was started.
        service = harness.model.unit.get_container("temporal").get_service("temporal")
        self.assertTrue(service.is_running())

        # The ActiveStatus is set with no message.
        self.assertEqual(harness.model.unit.status, ActiveStatus())

    def test_config_changed(self):
        """The pebble plan changes according to config changes."""
        harness = self.harness
        simulate_lifecycle(harness)

        # Update the config.
        self.harness.update_config({"log-level": "debug", "services": "worker"})

        # The new plan reflects the change.
        want_plan = {
            "services": {
                "temporal": {
                    "summary": "temporal server",
                    "command": "temporal-server --env charm start --service=worker",
                    "startup": "enabled",
                    "override": "replace",
                    "environment": {
                        "DB_HOST": "myhost",
                        "DB_NAME": "temporal-k8s_db",
                        "DB_PORT": "5432",
                        "DB_PSWD": "inner-light",
                        "DB_USER": "jean-luc@db",
                        "VISIBILITY_HOST": "myhost",
                        "VISIBILITY_NAME": "temporal-k8s_visibility",
                        "VISIBILITY_PORT": "5432",
                        "VISIBILITY_PSWD": "inner-light",
                        "VISIBILITY_USER": "jean-luc@visibility",
                        "LOG_LEVEL": "debug",
                    },
                }
            },
        }
        got_plan = harness.get_container_pebble_plan("temporal").to_dict()
        self.assertEqual(got_plan, want_plan)

        # The ActiveStatus is set with no message.
        self.assertEqual(harness.model.unit.status, ActiveStatus())

    def test_invalid_config_value(self):
        """The charm blocks if an invalid config value is provided."""
        harness = self.harness
        simulate_lifecycle(harness)

        # Update the config with an invalid value.
        self.harness.update_config({"services": "worker,bad-wolf"})

        # The change is not applied to the plan.
        want_command = (
            "temporal-server --env charm start --service=frontend --service=history --service=matching --service=worker"
        )
        got_command = harness.get_container_pebble_plan("temporal").to_dict()["services"]["temporal"]["command"]
        self.assertEqual(got_command, want_command)

        # The BlockStatus is set with a message.
        self.assertEqual(
            harness.model.unit.status,
            BlockedStatus("error in services config: invalid service 'bad-wolf'"),
        )

    def test_database_connections(self):
        """The method returns database connections as a dict."""
        harness = self.harness
        simulate_lifecycle(harness)

        database_connections = harness.charm.database_connections()
        self.assertEqual(
            database_connections,
            {
                "db": {
                    "dbname": "temporal-k8s_db",
                    "host": "myhost",
                    "password": "inner-light",
                    "port": "5432",
                    "user": "jean-luc@db",
                },
                "visibility": {
                    "dbname": "temporal-k8s_visibility",
                    "host": "myhost",
                    "password": "inner-light",
                    "port": "5432",
                    "user": "jean-luc@visibility",
                },
            },
        )
        self.assertIsInstance(database_connections, dict)
        for v in database_connections.values():
            self.assertIsInstance(v, dict)

    def test_ingress(self):
        """The charm relates correctly to the nginx ingress charm and can be configured."""
        harness = self.harness

        simulate_lifecycle(harness)

        nginx_route_relation_id = harness.add_relation("nginx-route", "ingress")
        harness.charm._require_nginx_route()

        assert harness.get_relation_data(nginx_route_relation_id, harness.charm.app) == {
            "service-namespace": harness.charm.model.name,
            "service-hostname": harness.charm.app.name,
            "service-name": harness.charm.app.name,
            "service-port": SERVER_PORT,
            "backend-protocol": "GRPC",
            "tls-secret-name": "temporal-tls",
        }

        new_hostname = "new-temporal-k8s"
        harness.update_config({"external-hostname": new_hostname})
        harness.charm._require_nginx_route()

        assert harness.get_relation_data(nginx_route_relation_id, harness.charm.app) == {
            "service-namespace": harness.charm.model.name,
            "service-hostname": new_hostname,
            "service-name": harness.charm.app.name,
            "service-port": SERVER_PORT,
            "backend-protocol": "GRPC",
            "tls-secret-name": "temporal-tls",
        }

        new_tls = "new-tls"
        harness.update_config({"tls-secret-name": new_tls})
        harness.charm._require_nginx_route()

        assert harness.get_relation_data(nginx_route_relation_id, harness.charm.app) == {
            "service-namespace": harness.charm.model.name,
            "service-hostname": new_hostname,
            "service-name": harness.charm.app.name,
            "service-port": SERVER_PORT,
            "backend-protocol": "GRPC",
            "tls-secret-name": new_tls,
        }


def simulate_lifecycle(harness):
    """Simulate a healthy charm life-cycle.

    Args:
        harness: ops.testing.Harness object used to simulate charm lifecycle.
    """
    # Simulate peer relation readiness.
    harness.add_relation("peer", "temporal")

    # Simulate pebble readiness.
    container = harness.model.unit.get_container("temporal")
    harness.charm.on.temporal_pebble_ready.emit(container)

    # Simulate db readiness.
    event = make_database_changed_event("db")
    harness.charm._on_database_changed(event)

    # Simulate visibility readiness.
    event = make_database_changed_event("visibility")
    harness.charm._on_database_changed(event)

    # Simulate schema readiness.
    app = type("App", (), {"name": "temporal-k8s"})()
    relation = type("Relation", (), {"data": {app: {"schema_status": "ready"}}, "name": "admin", "id": 42})()
    unit = type("Unit", (), {"app": app, "name": "temporal-k8s/0"})()
    event = type("Event", (), {"app": app, "relation": relation, "unit": unit})()
    harness.charm.admin._on_admin_relation_changed(event)


def make_database_changed_event(rel_name):
    """Create and return a mock master changed event.

        The event is generated by the relation with the given name.

    Args:
        rel_name: Name of the database relation (db or visibility)

    Returns:
        Event dict.
    """
    return type(
        "Event",
        (),
        {
            "endpoints": "myhost:5432,anotherhost:2345",
            "username": f"jean-luc@{rel_name}",
            "password": "inner-light",
            "relation": type("Relation", (), {"name": rel_name}),
        },
    )


class TestState(TestCase):
    """Unit tests for state.

    Attrs:
        maxDiff: Specifies max difference shown by failed tests.
    """

    maxDiff = None

    def test_get(self):
        """It is possible to retrieve attributes from the state."""
        state = make_state({"foo": json.dumps("bar")})
        self.assertEqual(state.foo, "bar")
        self.assertIsNone(state.bad)

    def test_set(self):
        """It is possible to set attributes in the state."""
        data = {"foo": json.dumps("bar")}
        state = make_state(data)
        state.foo = 42
        state.list = [1, 2, 3]
        self.assertEqual(state.foo, 42)
        self.assertEqual(state.list, [1, 2, 3])
        self.assertEqual(data, {"foo": "42", "list": "[1, 2, 3]"})

    def test_del(self):
        """It is possible to unset attributes in the state."""
        data = {"foo": json.dumps("bar"), "answer": json.dumps(42)}
        state = make_state(data)
        del state.foo
        self.assertIsNone(state.foo)
        self.assertEqual(data, {"answer": "42"})
        # Deleting a name that is not set does not error.
        del state.foo

    def test_is_ready(self):
        """The state is not ready when it is not possible to get relations."""
        state = make_state({})
        self.assertTrue(state.is_ready())

        state = State("myapp", lambda: None)
        self.assertFalse(state.is_ready())


def make_state(data):
    """Create state object.

    Args:
        data: Data to be included in state.

    Returns:
        State object with data.
    """
    app = "myapp"
    rel = type("Rel", (), {"data": {app: data}})()
    return State(app, lambda: rel)
