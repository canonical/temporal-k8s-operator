# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.
#
# Learn more about testing at: https://juju.is/docs/sdk/testing


"""Temporal charm unit tests."""

# pylint:disable=protected-access,too-many-public-methods

from textwrap import dedent
from unittest import TestCase, mock

from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus
from ops.pebble import CheckStatus
from ops.testing import Harness

from charm import TemporalK8SCharm, render

SERVER_PORT = "7233"
mock_incomplete_pebble_plan = {"services": {"temporal": {"override": "replace"}}}


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
        self.harness.add_network("10.0.0.10", endpoint="peer")
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

    def test_blocked_by_missing_num_history_shards(self):
        """The charm is blocked because of a missing number of history shards in config."""
        harness = self.harness

        # Simulate peer relation readiness.
        harness.add_relation("peer", "temporal")

        # Simulate pebble readiness.
        container = harness.model.unit.get_container("temporal")
        harness.charm.on.temporal_pebble_ready.emit(container)

        # The BlockStatus is set with a message.
        self.assertEqual(
            harness.model.unit.status,
            BlockedStatus("value of 'num-history-shards' config must be set to a positive power of 2 (e.g. 1, 2, 4)"),
        )

    def test_blocked_by_db(self):
        """The charm is blocked without a db:pgsql relation with a ready master."""
        harness = self.harness

        # Simulate peer relation readiness.
        harness.add_relation("peer", "temporal")

        harness.update_config({"num-history-shards": 1})

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
        harness.add_relation("peer", "temporal")

        harness.update_config({"num-history-shards": 1})

        # Simulate pebble readiness.
        container = harness.model.unit.get_container("temporal")
        harness.charm.on.temporal_pebble_ready.emit(container)

        # Simulate db readiness.
        simulate_db_relation(harness, "db")

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
        harness.add_relation("peer", "temporal")

        harness.update_config({"num-history-shards": 1})

        # Simulate pebble readiness.
        container = harness.model.unit.get_container("temporal")
        harness.charm.on.temporal_pebble_ready.emit(container)

        # Simulate db readiness.
        simulate_db_relation(harness, "db")

        # Simulate visibility readiness.
        simulate_db_relation(harness, "visibility")

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
                    "--service=frontend --service=history --service=matching --service=worker --service=internal-frontend",
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
                        "TEMPORAL_BROADCAST_ADDRESS": str(
                            self.harness.model.get_binding("peer").network.ingress_address
                        ),
                        "NUM_HISTORY_SHARDS": 1,
                        "SQL_TLS_ENABLED": False,
                        "SQL_MAX_CONNS": 20,
                        "SQL_MAX_IDLE_CONNS": 20,
                        "SQL_MAX_CONN_TIME": "1h",
                        "SQL_VIS_MAX_CONNS": 10,
                        "SQL_VIS_MAX_IDLE_CONNS": 10,
                        "SQL_VIS_MAX_CONN_TIME": "1h",
                    },
                    "on-check-failure": {"up": "ignore"},
                },
            },
            "checks": {
                "up": {
                    "exec": {"command": "tctl --address=temporal-k8s:7236 cluster health"},
                    "level": "alive",
                    "override": "replace",
                    "period": "300s",
                }
            },
        }
        got_plan = harness.get_container_pebble_plan("temporal").to_dict()
        self.assertEqual(got_plan, want_plan)

        # The service was started.
        service = harness.model.unit.get_container("temporal").get_service("temporal")
        self.assertTrue(service.is_running())

        self.assertEqual(harness.model.unit.status, MaintenanceStatus("replanning application"))

    def test_blocked_by_setting_new_num_history_shards(self):
        """The charm is blocked because of setting a new number of history shards in config."""
        harness = self.harness
        simulate_lifecycle(harness)

        container = harness.model.unit.get_container("temporal")
        container.get_check = mock.Mock(status="up")
        container.get_check.return_value.status = CheckStatus.UP
        harness.charm.on.update_status.emit()

        harness.update_config({"num-history-shards": 4})

        # The BlockStatus is set with a message.
        self.assertEqual(
            harness.model.unit.status,
            BlockedStatus("value of 'num-history-shards' config cannot be changed after deployment. Value should be 1"),
        )

    @mock.patch("relations.s3_archival._create_bucket_if_not_exists", return_value=None)
    def test_s3_archival_relation(self, _create_bucket_if_not_exists):
        """The pebble plan is correctly generated when the charm is ready."""
        harness = self.harness
        simulate_lifecycle(harness)

        relation_id = harness.add_relation("s3-parameters", "temporal")
        harness.update_relation_data(
            relation_id,
            "temporal",
            s3_provider_databag(),
        )

        # The plan is generated after pebble is ready.
        want_plan = {
            "services": {
                "temporal": {
                    "summary": "temporal server",
                    "command": "temporal-server --env charm start "
                    "--service=frontend --service=history --service=matching --service=worker --service=internal-frontend",
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
                        "TEMPORAL_BROADCAST_ADDRESS": str(
                            self.harness.model.get_binding("peer").network.ingress_address
                        ),
                        "NUM_HISTORY_SHARDS": 1,
                        "SQL_MAX_CONNS": 20,
                        "SQL_TLS_ENABLED": False,
                        "SQL_MAX_IDLE_CONNS": 20,
                        "SQL_MAX_CONN_TIME": "1h",
                        "SQL_VIS_MAX_CONNS": 10,
                        "SQL_VIS_MAX_IDLE_CONNS": 10,
                        "SQL_VIS_MAX_CONN_TIME": "1h",
                        "ARCHIVAL_ENABLED": True,
                        "ARCHIVAL_BUCKET_REGION": "region",
                        "ARCHIVAL_ENDPOINT": "endpoint",
                        "ARCHIVAL_URI_STYLE": "path",
                        "AWS_ACCESS_KEY_ID": "access",
                        "AWS_SECRET_ACCESS_KEY": "secret",
                    },
                    "on-check-failure": {"up": "ignore"},
                },
            },
            "checks": {
                "up": {
                    "exec": {"command": "tctl --address=temporal-k8s:7236 cluster health"},
                    "level": "alive",
                    "override": "replace",
                    "period": "300s",
                }
            },
        }
        got_plan = harness.get_container_pebble_plan("temporal").to_dict()
        self.assertEqual(got_plan, want_plan)

        # The service was started.
        service = harness.model.unit.get_container("temporal").get_service("temporal")
        self.assertTrue(service.is_running())

        self.assertEqual(harness.model.unit.status, MaintenanceStatus("replanning application"))

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
                        "TEMPORAL_BROADCAST_ADDRESS": str(
                            self.harness.model.get_binding("peer").network.ingress_address
                        ),
                        "NUM_HISTORY_SHARDS": 1,
                        "SQL_TLS_ENABLED": False,
                        "SQL_MAX_CONNS": 20,
                        "SQL_MAX_IDLE_CONNS": 20,
                        "SQL_MAX_CONN_TIME": "1h",
                        "SQL_VIS_MAX_CONNS": 10,
                        "SQL_VIS_MAX_IDLE_CONNS": 10,
                        "SQL_VIS_MAX_CONN_TIME": "1h",
                    },
                    "on-check-failure": {"up": "ignore"},
                },
            },
            "checks": {
                "up": {
                    "exec": {"command": "tctl --address=temporal-k8s:7236 cluster health"},
                    "level": "alive",
                    "override": "replace",
                    "period": "300s",
                }
            },
        }
        got_plan = harness.get_container_pebble_plan("temporal").to_dict()
        self.assertEqual(got_plan, want_plan)

        self.assertEqual(harness.model.unit.status, MaintenanceStatus("replanning application"))

    def test_invalid_config_value(self):
        """The charm blocks if an invalid config value is provided."""
        harness = self.harness
        simulate_lifecycle(harness)

        # Update the config with an invalid value.
        self.harness.update_config({"services": "worker,bad-wolf"})

        # The change is not applied to the plan.
        want_command = "temporal-server --env charm start --service=frontend --service=history --service=matching --service=worker --service=internal-frontend"
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

    def test_blocked_by_openfga_store(self):
        """When openfga store created event is not fired container charm is blocked."""
        harness = self.harness

        simulate_lifecycle(harness)
        harness.update_config({"auth-enabled": True})

        # database relation ready but no openfga store set up
        self.assertEqual(harness.model.unit.status, BlockedStatus("openfga:temporal relation not ready"))

    def test_blocked_by_authorization_model(self):
        """When openfga store created event is not fired container charm is blocked."""
        harness = self.harness

        simulate_lifecycle(harness)
        simulate_auth_lifecycle(harness, include_auth_model=False)

        # database relation ready but no openfga store set up
        self.assertEqual(harness.model.unit.status, BlockedStatus("missing openfga authorization model"))

    def test_authorization_ready(self):
        """When openfga store created event is not fired container charm is blocked."""
        harness = self.harness

        simulate_lifecycle(harness)
        simulate_auth_lifecycle(harness)

        # The plan is generated after pebble is ready.
        want_plan = {
            "services": {
                "temporal": {
                    "summary": "temporal server",
                    "command": "temporal-server --env charm start "
                    "--service=frontend --service=history --service=matching --service=worker --service=internal-frontend",
                    "startup": "enabled",
                    "override": "replace",
                    "environment": {
                        "AUTH_ENABLED": True,
                        "AUTH_GOOGLE_CLIENT_ID": "",
                        "AUTH_OPEN_ACCESS_NAMESPACES": "",
                        "AUTH_ADMIN_GROUPS": "",
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
                        "TEMPORAL_BROADCAST_ADDRESS": str(
                            self.harness.model.get_binding("peer").network.ingress_address
                        ),
                        "NUM_HISTORY_SHARDS": 1,
                        "SQL_TLS_ENABLED": False,
                        "SQL_MAX_CONNS": 20,
                        "SQL_MAX_IDLE_CONNS": 20,
                        "SQL_MAX_CONN_TIME": "1h",
                        "SQL_VIS_MAX_CONNS": 10,
                        "SQL_VIS_MAX_IDLE_CONNS": 10,
                        "SQL_VIS_MAX_CONN_TIME": "1h",
                        "OFGA_STORE_ID": harness.charm._state.openfga["store_id"],
                        "OFGA_AUTH_MODEL_ID": harness.charm._state.openfga["auth_model_id"],
                        "OFGA_API_HOST": harness.charm._state.openfga["address"],
                        "OFGA_API_SCHEME": harness.charm._state.openfga["scheme"],
                        "OFGA_SECRETS_BEARER_TOKEN": harness.charm._state.openfga["token"],
                        "OFGA_API_PORT": harness.charm._state.openfga["port"],
                    },
                    "on-check-failure": {"up": "ignore"},
                }
            },
            "checks": {
                "up": {
                    "exec": {"command": "tctl --address=temporal-k8s:7236 cluster health"},
                    "level": "alive",
                    "override": "replace",
                    "period": "300s",
                }
            },
        }
        got_plan = harness.get_container_pebble_plan("temporal").to_dict()
        self.assertEqual(got_plan, want_plan)

        self.assertEqual(harness.model.unit.status, MaintenanceStatus("replanning application"))
        container = harness.model.unit.get_container("temporal")
        container.get_check = mock.Mock(status="up")
        container.get_check.return_value.status = CheckStatus.UP
        harness.charm.on.update_status.emit()
        self.assertEqual(harness.model.unit.status, ActiveStatus("auth enabled"))

    def test_update_status_up(self):
        """The charm updates the unit status to active based on UP status."""
        harness = self.harness

        simulate_lifecycle(harness)
        simulate_auth_lifecycle(harness)

        container = harness.model.unit.get_container("temporal")
        container.get_check = mock.Mock(status="up")
        container.get_check.return_value.status = CheckStatus.UP
        harness.charm.on.update_status.emit()

        self.assertEqual(harness.model.unit.status, ActiveStatus("auth enabled"))

    def test_update_status_down(self):
        """The charm updates the unit status to maintenance based on DOWN status."""
        harness = self.harness

        simulate_lifecycle(harness)

        container = harness.model.unit.get_container("temporal")
        container.get_check = mock.Mock(status="up")
        container.get_check.return_value.status = CheckStatus.DOWN
        harness.charm.on.update_status.emit()

        self.assertEqual(harness.model.unit.status, MaintenanceStatus("Status check: DOWN"))

    def test_incomplete_pebble_plan(self):
        """The charm re-applies the pebble plan if incomplete."""
        harness = self.harness
        simulate_lifecycle(harness)

        container = harness.model.unit.get_container("temporal")
        container.add_layer("temporal", mock_incomplete_pebble_plan, combine=True)
        harness.charm.on.update_status.emit()

        self.assertEqual(
            harness.model.unit.status,
            MaintenanceStatus("replanning application"),
        )
        plan = harness.get_container_pebble_plan("temporal").to_dict()
        assert plan != mock_incomplete_pebble_plan

    @mock.patch("charm.TemporalK8SCharm._validate_pebble_plan", return_value=True)
    def test_missing_pebble_plan(self, mock_validate_pebble_plan):
        """The charm re-applies the pebble plan if missing."""
        harness = self.harness
        simulate_lifecycle(harness)

        mock_validate_pebble_plan.return_value = False
        harness.charm.on.update_status.emit()
        self.assertEqual(
            harness.model.unit.status,
            MaintenanceStatus("replanning application"),
        )
        plan = harness.get_container_pebble_plan("temporal").to_dict()
        assert plan is not None

    def test_rendering(self):
        """The dynamic config gets rendered correctly."""
        expected_output = dedent(
            """
        frontend.namespacerps:
        - value: 500


        - value: 50
          constraints:
            namespace: "namespaceA"


        - value: 100
          constraints:
            namespace: "namespaceB"


        - value: 200
          constraints:
            namespace: "namespaceC"
        """
        ).strip()

        dynamic_context = {
            "GLOBAL_RPS_LIMIT": 500,
            "NAMESPACE_RPS_LIMIT": "namespaceA:50|namespaceB:100|namespaceC:200",
        }

        dynamic_config = render("dynamic_config.jinja", dynamic_context).strip()
        self.assertEqual(dedent(dynamic_config).strip(), expected_output)


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
    simulate_db_relation(harness, "db")

    # Simulate visibility readiness.
    simulate_db_relation(harness, "visibility")

    harness.update_config({"num-history-shards": 1})

    # Simulate schema readiness.
    app = type("App", (), {"name": "temporal-k8s"})()
    relation = type("Relation", (), {"data": {app: {"schema_status": "ready"}}, "name": "admin", "id": 42})()
    unit = type("Unit", (), {"app": app, "name": "temporal-k8s/0"})()
    event = type("Event", (), {"app": app, "relation": relation, "unit": unit})()
    harness.charm.admin._on_admin_relation_changed(event)


def simulate_db_relation(harness, rel_name):
    """Simulate a db relation with the postgresql charm.

    Args:
        harness: ops.testing.Harness object used to simulate charm lifecycle.
        rel_name: name of DB relation.
    """
    db_relation_id = harness.add_relation(rel_name, "postgresql")

    relation_data = {
        "database": f"temporal-k8s_{rel_name}",
        "endpoints": "myhost:5432,anotherhost:2345",
        "password": "inner-light",
        "username": f"jean-luc@{rel_name}",
    }

    harness.update_relation_data(
        db_relation_id,
        "postgresql",
        relation_data,
    )


def simulate_auth_lifecycle(harness, include_auth_model=True):
    """Simulate a charm life-cycle with auth enabled.

    Args:
        harness: ops.testing.Harness object used to simulate charm lifecycle.
        include_auth_model: whether or not to include the auth model id in the harness.
    """
    harness.update_config({"auth-enabled": True})

    relation_id = harness.add_relation("openfga", "temporal")
    secret_id = harness.add_model_secret("temporal-k8s", {"token": "openfga_token"})
    event = make_openfga_store_created_event(secret_id)
    harness.charm.openfga_relation._on_openfga_store_created(event)
    harness.update_relation_data(
        relation_id,
        "temporal",
        openfga_provider_databag(secret_id),
    )

    if include_auth_model:
        harness.charm._state.openfga = {
            **harness.charm._state.openfga,
            "auth_model_id": "123",
        }

    harness.update_config({})


def make_openfga_store_created_event(token_secret_id):
    """Create and return a mock master changed event for OpenFGA.

    The event is generated by the relation with the given name.

    Args:
        token_secret_id: Secret ID where token is stored in the model.

    Returns:
        Event dict.
    """
    return type(
        "Event",
        (),
        {
            "store_id": "storeid12345",
            "relation": type("Relation", (), {"name": "openfga"}),
        },
    )


def openfga_provider_databag(token_secret_id):
    """Create and return mock store info.

    Args:
        token_secret_id: Secret ID where token is stored in the model.

    Returns:
        Store info.
    """
    return {
        "store_id": "storeid12345",
        "token_secret_id": token_secret_id,
        "address": "127.0.0.1",
        "scheme": "http",
        "port": "8080",
        "http_api_url": "http://127.0.0.1:8080",
        "grpc_api_url": "http://127.0.0.1:8081",
    }


def s3_provider_databag():
    """Create and return mock s3 credentials.

    Returns:
        S3 parameters.
    """
    return {
        "access-key": "access",
        "secret-key": "secret",
        "bucket": "bucket_name",
        "endpoint": "endpoint",
        "path": "path",
        "region": "region",
        "s3-uri-style": "path",
    }
