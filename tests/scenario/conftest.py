# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import json

import ops.testing
import pytest

from charm import TemporalK8SCharm


def pytest_configure(config):  # noqa: DCO020
    """Flags that can be configured to modify fixture behavior.

    Used to determine how _state in the peer relation app databag is populated.

    Args:
        config: the pytest config object
    """
    config.addinivalue_line("markers", "peer_relation_skipped")
    config.addinivalue_line("markers", "config_skipped")
    config.addinivalue_line("markers", "db_relation_skipped")
    config.addinivalue_line("markers", "visibility_relation_skipped")
    config.addinivalue_line("markers", "parametrize_skip_if")
    config.addinivalue_line("markers", "s3_relation_skipped")
    config.addinivalue_line("markers", "openfga_auth_skipped")
    config.addinivalue_line("markers", "openfga_uninitialized")


def pytest_runtest_setup(item):
    """Supports the ability to skip tests based on the leader parameter.

    Args:
        item: the test invocation item
    """
    skip_funcs = [mark.args[0] for mark in item.iter_markers(name="parametrize_skip_if")]
    if any(f(leader=item.callspec.params["state"]) for f in skip_funcs):
        pytest.skip()


@pytest.fixture
def temporal_k8s_charm():
    yield TemporalK8SCharm


@pytest.fixture(scope="function")
def context(temporal_k8s_charm):
    return ops.testing.Context(charm_type=temporal_k8s_charm)


@pytest.fixture(scope="function")
def temporal_container():
    return ops.testing.Container(
        "temporal",
        can_connect=True,
    )


@pytest.fixture(scope="function")
def temporal_container_initialized():
    return ops.testing.Container(
        "temporal",
        can_connect=True,
        check_infos=[ops.testing.CheckInfo("up")],
        layers={
            "initialized-layer": ops.pebble.Layer(
                {
                    "checks": {
                        "up": ops.pebble.CheckDict(
                            exec=ops.pebble.ExecDict(
                                command="tctl --address=temporal-k8s:7236 cluster health",
                            ),
                            level=None,
                            override="replace",
                            period="300s",
                            startup=ops.pebble.CheckStartup.ENABLED,
                            threshold=3,
                        ),
                    },
                }
            ),
        },
    )


@pytest.fixture(scope="function")
def incomplete_layer_dict():
    return {
        "services": {
            "temporal": {
                "override": "replace",
            },
        },
    }


@pytest.fixture(scope="function")
def temporal_container_incomplete_layer(incomplete_layer_dict):
    return ops.testing.Container(
        "temporal",
        can_connect=True,
        layers={
            "incomplete-layer": ops.pebble.Layer(incomplete_layer_dict),
        },
    )


@pytest.fixture(scope="function")
def network():
    return ops.testing.Network(
        binding_name="peer",
        bind_addresses=[
            ops.testing.BindAddress(
                addresses=[
                    ops.testing.Address(
                        value="1.2.3.4",
                    ),
                ],
            ),
        ],
    )


@pytest.fixture(scope="function")
def openfga_secret():
    return ops.testing.Secret(
        owner="app",
        tracked_content={
            "token": "openfga_token",
        },
    )


@pytest.fixture(scope="function")
def openfga_store_id():
    return "storeid12345"


@pytest.fixture(scope="function")
def openfga_data(openfga_secret, openfga_store_id):
    return {
        "store_id": openfga_store_id,
        "token_secret_id": openfga_secret.id,
        "address": "127.0.0.1",
        "scheme": "http",
        "port": "8080",
        "http_api_url": "http://127.0.0.1:8080",
        "grpc_api_url": "http://127.0.0.1:8081",
    }


@pytest.fixture(scope="function")
def s3_config():
    return {
        "access-key": "access",
        "secret-key": "secret",
        "bucket": "bucket_name",
        "endpoint": "s3.us-east-2.amazonaws.com ",
        "path": "path",
        "region": "region",
        "s3-uri-style": "path",
    }


@pytest.fixture(scope="function")
def postgres_db_data():
    return {
        "database": "temporal-k8s_db",
        "endpoints": "myhost:5432,anotherhost:2345",
        "password": "inner-light",
        "username": "jean-luc@db",
    }


@pytest.fixture(scope="function")
def postgres_visibility_data():
    return {
        "database": "temporal-k8s_visibility",
        "endpoints": "myhost:5432,anotherhost:2345",
        "password": "inner-light",
        "username": "jean-luc@visibility",
    }


@pytest.fixture(scope="function")
def tls_certificates_data():
    return {
        "certificates": json.dumps(
            [
                {
                    "ca": "some-ca-cert",
                    "certificate_signing_request": "some-csr",
                    "certificate": "some-cert",
                    "chain": ["some-chain", "some-other-val"],
                }
            ]
        )
    }


@pytest.fixture(scope="function")
def peer_relation(request, s3_config, openfga_store_id, openfga_secret):
    if request.node.get_closest_marker("peer_relation_skipped"):
        return ops.testing.Relation(endpoint="peer")

    state_data, database_connections_data = {}, {}

    if not request.node.get_closest_marker("config_skipped"):
        state_data["num_history_shards"] = "1"

    db_data = {
        "dbname": "temporal-k8s_db",
        "host": "myhost",
        "port": "5432",
        "password": "inner-light",
        "user": "jean-luc@db",
        "tls": False,
    }

    visibility_data = {
        "dbname": "temporal-k8s_visibility",
        "host": "myhost",
        "port": "5432",
        "password": "inner-light",
        "user": "jean-luc@visibility",
        "tls": False,
    }

    database_connections_data["db"] = db_data if not request.node.get_closest_marker("db_relation_skipped") else None
    database_connections_data["visibility"] = (
        visibility_data if not request.node.get_closest_marker("visibility_relation_skipped") else None
    )
    state_data["database_connections"] = json.dumps(database_connections_data)

    if not request.node.get_closest_marker("s3_relation_skipped"):
        state_data["s3"] = json.dumps(
            {
                "bucket": s3_config["bucket"],
                "endpoint": "s3.us-east-2.amazonaws.com",
                "region": s3_config["region"],
                "aws_access_key_id": s3_config["access-key"],
                "aws_secret_access_key": s3_config["secret-key"],
                "uri_style": s3_config["s3-uri-style"],
                "bucket_created": True,
            }
        )

    if not request.node.get_closest_marker("openfga_uninitialized"):
        state_data["openfga"] = json.dumps(
            {
                "store_id": openfga_store_id,
                "token": openfga_secret.id,
                "address": "127.0.0.1",
                "port": "8080",
                "scheme": "http",
                "auth_model_id": None if request.node.get_closest_marker("openfga_auth_skipped") else "123",
            }
        )

    return ops.testing.PeerRelation(endpoint="peer", local_app_data=state_data)


@pytest.fixture(scope="function")
def admin_relation():
    return ops.testing.Relation("admin", remote_app_data={"schema_status": "ready"})


@pytest.fixture(scope="function")
def frontend_certificates_relation():
    return ops.testing.Relation("frontend-certificates")


@pytest.fixture(scope="function")
def db_relation(postgres_db_data):
    return ops.testing.Relation("db", remote_app_data=postgres_db_data)


@pytest.fixture(scope="function")
def visibility_relation(postgres_visibility_data):
    return ops.testing.Relation("visibility", remote_app_data=postgres_visibility_data)


@pytest.fixture(scope="function")
def traefik_ingress_relation():
    return ops.testing.Relation("ingress")


@pytest.fixture(scope="function")
def nginx_route_relation():
    return ops.testing.Relation("nginx-route")


@pytest.fixture(scope="function")
def openfga_relation(openfga_data):
    return ops.testing.Relation("openfga", remote_app_data=openfga_data)


@pytest.fixture(scope="function")
def s3_relation(s3_config):
    return ops.testing.Relation("s3-parameters", remote_app_data=s3_config)
