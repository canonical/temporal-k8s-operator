# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
#
# Learn more about testing at: https://juju.is/docs/sdk/testing


"""Temporal charm unit tests."""

# pylint:disable=protected-access

from unittest import TestCase

from ops.model import ActiveStatus, BlockedStatus
from ops.testing import Harness

from charm import TemporalK8SCharm


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
        event = make_master_changed_event("db")
        harness.charm._on_master_changed(event)

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
        event = make_master_changed_event("db")
        harness.charm._on_master_changed(event)

        # Simulate visibility readiness.
        event = make_master_changed_event("visibility")
        harness.charm._on_master_changed(event)

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
                        "DB_PORT": "4247",
                        "DB_PSWD": "inner-light",
                        "DB_USER": "jean-luc@db",
                        "VISIBILITY_HOST": "myhost",
                        "VISIBILITY_NAME": "temporal-k8s_visibility",
                        "VISIBILITY_PORT": "4247",
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
                        "DB_PORT": "4247",
                        "DB_PSWD": "inner-light",
                        "DB_USER": "jean-luc@db",
                        "VISIBILITY_HOST": "myhost",
                        "VISIBILITY_NAME": "temporal-k8s_visibility",
                        "VISIBILITY_PORT": "4247",
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
                    "port": "4247",
                    "user": "jean-luc@db",
                },
                "visibility": {
                    "dbname": "temporal-k8s_visibility",
                    "host": "myhost",
                    "password": "inner-light",
                    "port": "4247",
                    "user": "jean-luc@visibility",
                },
            },
        )
        self.assertIsInstance(database_connections, dict)
        for v in database_connections.values():
            self.assertIsInstance(v, dict)


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
    event = make_master_changed_event("db")
    harness.charm._on_master_changed(event)

    # Simulate visibility readiness.
    event = make_master_changed_event("visibility")
    harness.charm._on_master_changed(event)

    # Simulate schema readiness.
    app = type("App", (), {"name": "temporal-k8s"})()
    relation = type("Relation", (), {"data": {app: {"schema_status": "ready"}}, "name": "admin", "id": 42})()
    unit = type("Unit", (), {"app": app, "name": "temporal-k8s/0"})()
    event = type("Event", (), {"app": app, "relation": relation, "unit": unit})()
    harness.charm.admin._on_admin_relation_changed(event)


def make_master_changed_event(rel_name):
    """Create and return a mock master changed event.

    The event is generated by the relation with the given name.

    Args:
        rel_name: Relationship name.

    Returns:
        Event dict.
    """
    return type(
        "Event",
        (),
        {
            "database": f"temporal-k8s_{rel_name}",
            "master": {
                "dbname": f"temporal-k8s_{rel_name}",
                "host": "myhost",
                "port": "4247",
                "user": f"jean-luc@{rel_name}",
                "password": "inner-light",
            },
            "relation": type("Relation", (), {"name": rel_name}),
        },
    )
