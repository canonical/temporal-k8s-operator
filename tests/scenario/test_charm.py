# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import dataclasses
import logging
import textwrap
import unittest.mock
from unittest.mock import MagicMock

import ops
import ops.testing
import pytest
from charms.tls_certificates_interface.v4.tls_certificates import (
    CertificateAvailableEvent,
    PrivateKey,
    ProviderCertificate,
)

from charm import (
    FRONTEND_CERTIFICATES_RELATION_NAME,
    FRONTEND_TLS_CONFIGURATION,
    render,
)

logger = logging.getLogger(__name__)


@pytest.fixture
def all_required_relations(
    peer_relation,
    admin_relation,
    db_relation,
    visibility_relation,
    nginx_route_relation,
    openfga_relation,
    s3_relation,
):
    return [
        peer_relation,
        admin_relation,
        db_relation,
        visibility_relation,
        nginx_route_relation,
        openfga_relation,
        s3_relation,
    ]


@pytest.fixture(params=[True, False], ids=["leader", "not leader"])
def state(
    request,
    temporal_container,
    all_required_relations,
    network,
    openfga_secret,
):
    return ops.testing.State(
        leader=request.param,
        containers=[temporal_container],
        config={"num-history-shards": 1},
        relations=all_required_relations,
        networks=[network],
        secrets=[openfga_secret],
    )


def test_smoke(context, state):
    context.run(context.on.start(), state)


@pytest.mark.peer_relation_skipped
def test_blocked_on_peer_relation_not_ready(context, state, temporal_container, all_required_relations, peer_relation):
    all_required_relations.remove(peer_relation)
    state = dataclasses.replace(state, relations=all_required_relations)

    state_out = context.run(context.on.pebble_ready(temporal_container), state)

    assert state_out.unit_status == ops.BlockedStatus("peer relation not ready")
    assert state_out.get_container("temporal").plan == {}


@pytest.mark.config_skipped
def test_blocked_by_missing_num_history_shards(context, state, temporal_container):
    state = dataclasses.replace(state, config={})

    state_out = context.run(context.on.pebble_ready(temporal_container), state)

    assert state_out.unit_status == ops.BlockedStatus(
        "value of 'num-history-shards' config must be set to a positive power of 2 (e.g. 1, 2, 4)"
    )
    assert state_out.get_container("temporal").plan == {}


@pytest.mark.db_relation_skipped
@pytest.mark.visibility_relation_skipped
def test_blocked_by_missing_database_relations(
    context, state, temporal_container, all_required_relations, db_relation, visibility_relation
):
    all_required_relations.remove(db_relation)
    all_required_relations.remove(visibility_relation)
    state = dataclasses.replace(state, relations=all_required_relations)

    state_out = context.run(context.on.pebble_ready(temporal_container), state)

    assert state_out.unit_status == ops.BlockedStatus("database relation not ready")
    assert state_out.get_container("temporal").plan == {}


@pytest.mark.db_relation_skipped
def test_blocked_by_missing_db_relation(context, state, temporal_container, all_required_relations, db_relation):
    all_required_relations.remove(db_relation)
    state = dataclasses.replace(state, relations=all_required_relations)

    state_out = context.run(context.on.pebble_ready(temporal_container), state)

    assert state_out.unit_status == ops.BlockedStatus("db:pgsql relation: no database connection available")
    assert state_out.get_container("temporal").plan == {}


@pytest.mark.visibility_relation_skipped
def test_blocked_by_missing_visibility_relation(
    context, state, temporal_container, all_required_relations, visibility_relation
):
    all_required_relations.remove(visibility_relation)
    state = dataclasses.replace(state, relations=all_required_relations)

    state_out = context.run(context.on.pebble_ready(temporal_container), state)

    assert state_out.unit_status == ops.BlockedStatus("visibility:pgsql relation: no database connection available")
    assert state_out.get_container("temporal").plan == {}


def test_admin_relation_not_ready(context, temporal_container, state, all_required_relations, admin_relation):
    # Replace admin relation with one that doesn't have schema_status=ready
    admin_not_ready = ops.testing.Relation("admin", remote_app_data={})
    relations = [r if r.endpoint != "admin" else admin_not_ready for r in all_required_relations]
    state = dataclasses.replace(state, relations=relations)

    state_out = context.run(context.on.pebble_ready(temporal_container), state)

    assert state_out.unit_status == ops.BlockedStatus("admin:temporal relation: schema is not ready")
    assert state_out.get_container("temporal").plan == {}


@pytest.mark.s3_relation_skipped
@pytest.mark.parametrize_skip_if(lambda leader: not leader)
def test_charm_ready(context, state, temporal_container, admin_relation):
    # In the reconciler pattern, pebble_ready reads admin databag directly.
    # With schema_status=ready in admin relation, the charm converges immediately.
    state_out = context.run(context.on.pebble_ready(temporal_container), state)

    assert state_out.unit_status == ops.ActiveStatus("")


@pytest.mark.parametrize_skip_if(lambda leader: not leader)
def test_blocked_by_setting_new_num_history_shards(context, state, temporal_container):
    # First reconcile to persist num_history_shards
    state_intermediate = context.run(context.on.pebble_ready(temporal_container), state)

    state_modified_config = dataclasses.replace(state_intermediate, config={"num-history-shards": 4})

    state_out = context.run(context.on.config_changed(), state_modified_config)

    assert state_out.unit_status == ops.BlockedStatus(
        "value of 'num-history-shards' config cannot be changed after deployment. Value should be 1"
    )


@pytest.mark.parametrize_skip_if(lambda leader: not leader)
def test_frontend_certificates_relation_broken(
    context,
    state,
    temporal_container,
    frontend_certificates_relation,
    all_required_relations,
):
    # Add frontend-certificates relation
    all_required_relations.append(frontend_certificates_relation)
    state = dataclasses.replace(state, relations=all_required_relations)

    # Initial reconcile
    new_state = context.run(context.on.pebble_ready(temporal_container), state)

    # Break the relation (use the relation from state_out)
    frontend_cert_rel = [r for r in new_state.relations if r.endpoint == "frontend-certificates"][0]
    new_state = context.run(context.on.relation_broken(frontend_cert_rel), new_state)

    # Check the pebble layer service does not contain any TLS variables
    assert (
        not FRONTEND_TLS_CONFIGURATION.items()
        <= new_state.get_container("temporal").plan.services["temporal-server"].environment.items()
    )


@pytest.mark.parametrize_skip_if(lambda leader: not leader)
def test_frontend_certificates_relation_blocked_on_not_frontend(
    context,
    state,
    temporal_container,
    frontend_certificates_relation,
    all_required_relations,
):
    # Add frontend-certificates relation with services=worker
    all_required_relations.append(frontend_certificates_relation)
    state = dataclasses.replace(
        state,
        relations=all_required_relations,
        config={"services": "worker", "num-history-shards": 1},
    )

    state_out = context.run(context.on.pebble_ready(temporal_container), state)

    assert state_out.unit_status == ops.BlockedStatus(
        f"Not a frontend service, please remove {FRONTEND_CERTIFICATES_RELATION_NAME} integration."
    )


@pytest.mark.parametrize_skip_if(lambda leader: not leader)
def test_frontend_certificates_relation(
    context,
    state,
    temporal_container,
    frontend_certificates_relation,
    all_required_relations,
):
    # Add frontend-certificates relation
    all_required_relations.append(frontend_certificates_relation)
    state = dataclasses.replace(state, relations=all_required_relations)

    # Mocks for certificates
    mocked_certificate = MagicMock()
    client_provider_certificate = MagicMock(ProviderCertificate)
    client_provider_certificate.certificate = mocked_certificate
    requirer_private_key = MagicMock(PrivateKey)

    with context(
        context.on.pebble_ready(temporal_container), state=state
    ) as manager, unittest.mock.patch(
        "charm.TemporalK8SCharm._update_certificates_required", return_value=True
    ), unittest.mock.patch(
        "charm.TemporalK8SCharm._store_certificate"
    ), unittest.mock.patch(
        "charm.TemporalK8SCharm._store_private_key"
    ):
        # Required mocks
        manager.charm.certificates.get_assigned_certificate = MagicMock(
            return_value=(client_provider_certificate, requirer_private_key)
        )

        state_out = manager.run()

        assert (
            FRONTEND_TLS_CONFIGURATION.items()
            <= state_out.get_container("temporal").plan.services["temporal-server"].environment.items()
        )


@pytest.mark.parametrize_skip_if(lambda leader: not leader)
def test_s3_archival_relation(
    context, state, temporal_container, s3_relation
):
    # In the reconciler, pebble_ready + all relations ready → reconciled fully
    # S3 state was already persisted in peer relation data by fixture
    state_out = context.run(context.on.pebble_ready(temporal_container), state)

    assert state_out.unit_status == ops.ActiveStatus("")

    expected_plan = {
        "services": {
            "temporal-server": {
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
                    "LOG_OUTPUT_FILE": "/var/log/temporal/server.log",
                    "LOG_FORMAT": "json",
                    "TEMPORAL_BROADCAST_ADDRESS": "1.2.3.4",
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
                    "ARCHIVAL_ENDPOINT": "s3.us-east-2.amazonaws.com",
                    "ARCHIVAL_URI_STYLE": "path",
                    "AWS_ACCESS_KEY_ID": "access",
                    "AWS_SECRET_ACCESS_KEY": "secret",
                },
                "on-check-failure": {"temporal-server-running": "ignore"},
                "user": "ubuntu",
                "working-dir": "/etc/temporal",
            },
        },
        "checks": {
            "temporal-server-running": {
                "exec": {"command": "temporal operator cluster health --address=temporal-k8s:7236"},
                "level": "alive",
                "override": "replace",
                "period": "300s",
                "threshold": 3,
            }
        },
    }
    assert state_out.get_container("temporal").plan.to_dict() == expected_plan
    assert (
        state_out.get_container("temporal").service_statuses["temporal-server"] == ops.pebble.ServiceStatus.ACTIVE
    )


@pytest.mark.parametrize_skip_if(lambda leader: not leader)
def test_invalid_config_value(
    context, state, temporal_container,
):
    # First reconcile to establish the pebble plan
    state_out = context.run(context.on.pebble_ready(temporal_container), state)

    # Now change config to include an invalid service
    state_modified_config = dataclasses.replace(state_out, config={"services": "worker,bad-wolf"})

    state_out = context.run(context.on.config_changed(), state_modified_config)

    # In the reconciler, the previous valid plan persists; the charm blocks on invalid config
    assert state_out.unit_status == ops.BlockedStatus("error in services config: invalid service 'bad-wolf'")


def test_database_connections(
    context, state, temporal_container,
):
    # Single step: pebble_ready converges fully in the reconciler
    with context(context.on.pebble_ready(temporal_container), state) as manager:
        state_out = manager.run()

        database_connections = {
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

        assert manager.charm.database_connections() == database_connections
        assert isinstance(database_connections, dict)
        for value in database_connections.values():
            assert isinstance(value, dict)


@pytest.mark.parametrize_skip_if(lambda leader: not leader)
def test_ingress(context, state, temporal_container):
    # Test nginx-route data with default config
    with context(context.on.pebble_ready(temporal_container), state) as manager:
        state_out = manager.run()

        assert state_out.get_relations("nginx-route")[0].local_app_data == {
            "service-namespace": manager.charm.model.name,
            "service-hostname": manager.charm.app.name,
            "service-name": manager.charm.app.name,
            "service-port": "7233",
            "backend-protocol": "GRPC",
            "tls-secret-name": "temporal-tls",
        }

    # Test nginx-route data with custom hostname
    state_updated = dataclasses.replace(
        state_out,
        config={"num-history-shards": 1, "external-hostname": "new-temporal-k8s"},
    )
    with context(context.on.config_changed(), state_updated) as manager:
        state_out = manager.run()

        assert state_out.get_relations("nginx-route")[0].local_app_data == {
            "service-namespace": manager.charm.model.name,
            "service-hostname": "new-temporal-k8s",
            "service-name": manager.charm.app.name,
            "service-port": "7233",
            "backend-protocol": "GRPC",
            "tls-secret-name": "temporal-tls",
        }

    # Test nginx-route data with custom tls-secret-name
    state_updated = dataclasses.replace(
        state_out,
        config={"num-history-shards": 1, "external-hostname": "new-temporal-k8s", "tls-secret-name": "new-tls"},
    )
    with context(context.on.config_changed(), state_updated) as manager:
        state_out = manager.run()

        assert state_out.get_relations("nginx-route")[0].local_app_data == {
            "service-namespace": manager.charm.model.name,
            "service-hostname": "new-temporal-k8s",
            "service-name": manager.charm.app.name,
            "service-port": "7233",
            "backend-protocol": "GRPC",
            "tls-secret-name": "new-tls",
        }


@pytest.mark.openfga_uninitialized
@pytest.mark.parametrize_skip_if(lambda leader: not leader)
def test_blocked_by_openfga_store(
    context,
    state,
    temporal_container,
    openfga_relation,
    all_required_relations,
):
    # Remove openfga relation and enable auth
    all_required_relations.remove(openfga_relation)
    state = dataclasses.replace(
        state,
        relations=all_required_relations,
        config={"num-history-shards": 1, "auth-enabled": True},
    )

    state_out = context.run(context.on.pebble_ready(temporal_container), state)

    assert state_out.unit_status == ops.BlockedStatus("openfga:temporal relation not ready")


@pytest.mark.openfga_auth_skipped
@pytest.mark.parametrize_skip_if(lambda leader: not leader)
def test_blocked_by_authorization_model(
    context, state, temporal_container,
):
    # Auth enabled but openfga has no auth_model_id (openfga_auth_skipped marker)
    state = dataclasses.replace(
        state,
        config={"num-history-shards": 1, "auth-enabled": True},
    )

    state_out = context.run(context.on.pebble_ready(temporal_container), state)

    assert state_out.unit_status == ops.BlockedStatus("missing openfga authorization model")


@pytest.mark.s3_relation_skipped
@pytest.mark.parametrize_skip_if(lambda leader: not leader)
def test_authorization_ready(
    context, state, temporal_container, openfga_store_id, openfga_secret
):
    # Auth enabled with full openfga setup (has auth_model_id)
    state = dataclasses.replace(
        state,
        config={"num-history-shards": 1, "auth-enabled": True},
    )

    state_out = context.run(context.on.pebble_ready(temporal_container), state)

    expected_plan = {
        "services": {
            "temporal-server": {
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
                    "LOG_OUTPUT_FILE": "/var/log/temporal/server.log",
                    "LOG_FORMAT": "json",
                    "TEMPORAL_BROADCAST_ADDRESS": "1.2.3.4",
                    "NUM_HISTORY_SHARDS": 1,
                    "SQL_TLS_ENABLED": False,
                    "SQL_MAX_CONNS": 20,
                    "SQL_MAX_IDLE_CONNS": 20,
                    "SQL_MAX_CONN_TIME": "1h",
                    "SQL_VIS_MAX_CONNS": 10,
                    "SQL_VIS_MAX_IDLE_CONNS": 10,
                    "SQL_VIS_MAX_CONN_TIME": "1h",
                    "OFGA_STORE_ID": openfga_store_id,
                    "OFGA_AUTH_MODEL_ID": "123",
                    "OFGA_API_HOST": "127.0.0.1",
                    "OFGA_API_SCHEME": "http",
                    "OFGA_SECRETS_BEARER_TOKEN": openfga_secret.id,
                    "OFGA_API_PORT": "8080",
                },
                "on-check-failure": {"temporal-server-running": "ignore"},
                "user": "ubuntu",
                "working-dir": "/etc/temporal",
            }
        },
        "checks": {
            "temporal-server-running": {
                "exec": {"command": "temporal operator cluster health --address=temporal-k8s:7236"},
                "level": "alive",
                "override": "replace",
                "period": "300s",
                "threshold": 3,
            },
        },
    }

    assert state_out.get_container("temporal").plan.to_dict() == expected_plan
    assert state_out.unit_status == ops.ActiveStatus("auth enabled")


@pytest.mark.parametrize_skip_if(lambda leader: not leader)
def test_update_status_down(context, state, temporal_container):
    # First reconcile to establish the pebble plan
    state_out = context.run(context.on.pebble_ready(temporal_container), state)

    # Replace the container check_infos to simulate DOWN health check
    # Must match plan values: level=alive, startup=unset
    temporal_container_down = dataclasses.replace(
        state_out.get_container("temporal"),
        check_infos=[
            ops.testing.CheckInfo(
                "temporal-server-running",
                status=ops.pebble.CheckStatus.DOWN,
                level=ops.pebble.CheckLevel.ALIVE,
                startup=ops.pebble.CheckStartup.UNSET,
            )
        ],
    )
    state_out = dataclasses.replace(state_out, containers=[temporal_container_down])

    state_out = context.run(context.on.update_status(), state_out)

    assert state_out.unit_status == ops.MaintenanceStatus("Status check: DOWN")


@pytest.mark.parametrize_skip_if(lambda leader: not leader)
def test_incomplete_pebble_plan(
    context, state, temporal_container, temporal_container_incomplete_layer, incomplete_layer_dict,
):
    # First reconcile to establish the full plan
    state_out = context.run(context.on.pebble_ready(temporal_container), state)

    # Replace the container with one that has an incomplete layer
    state_out = dataclasses.replace(state_out, containers=[temporal_container_incomplete_layer])

    # update_status → _reconcile detects plan mismatch and replans
    state_out = context.run(context.on.update_status(), state_out)

    # After replanning, the plan should be complete (not the incomplete one)
    assert state_out.get_container("temporal").plan.to_dict() != incomplete_layer_dict
    assert state_out.unit_status == ops.ActiveStatus("")


@pytest.mark.parametrize_skip_if(lambda leader: not leader)
def test_missing_pebble_plan(context, state, temporal_container):
    # First reconcile to establish the pebble plan
    state_out = context.run(context.on.pebble_ready(temporal_container), state)

    # Mock _validate_pebble_plan to return False (simulates plan validation failure)
    with unittest.mock.patch("charm.TemporalK8SCharm._validate_pebble_plan", return_value=False):
        state_out = context.run(context.on.update_status(), state_out)

        assert state_out.unit_status == ops.MaintenanceStatus("replanning application")
        assert state_out.get_container("temporal").plan.to_dict() is not None


def test_rendering():
    expected_output = textwrap.dedent(
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

        matching.longPollExpirationInterval:
          - value: "50s"

    """
    ).strip()

    dynamic_context = {
        "GLOBAL_RPS_LIMIT": 500,
        "NAMESPACE_RPS_LIMIT": "namespaceA:50|namespaceB:100|namespaceC:200",
        "LONG_POLL_INTERVAL": "50s",
    }

    dynamic_config = render("dynamic_config.jinja", dynamic_context).strip()
    assert textwrap.dedent(dynamic_config).strip() == expected_output
