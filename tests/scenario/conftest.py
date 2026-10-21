# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import dataclasses
import json
import types
import unittest.mock

import ops.testing
import pytest

from charm import TemporalK8SCharm
from relations.s3_archival import construct_endpoint, retrieve_s3_parameters


def s3_fingerprint(s3_config):
    """Return the fingerprint the charm records in the peer data for the S3 bucket.

    Args:
        s3_config: The S3 relation data.

    Returns:
        The fingerprint of the S3 state the charm derives from the relation data.
    """
    s3_parameters, _ = retrieve_s3_parameters(types.SimpleNamespace(get_s3_connection_info=lambda: dict(s3_config)))
    return TemporalK8SCharm._s3_fingerprint(
        {
            "bucket": s3_parameters["bucket"],
            "endpoint": construct_endpoint(s3_parameters),
            "region": s3_parameters["region"],
            "aws_access_key_id": s3_parameters["access-key"],
            "aws_secret_access_key": s3_parameters["secret-key"],
            "uri_style": s3_parameters["s3-uri-style"],
        }
    )


def pytest_configure(config):  # noqa: DCO020
    """Flags that can be configured to modify fixture behavior.

    Used to determine how the peer relation app databag is populated, and whether S3 is related.

    Args:
        config: the pytest config object
    """
    config.addinivalue_line("markers", "peer_relation_skipped")
    config.addinivalue_line("markers", "config_skipped")
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


@pytest.fixture(autouse=True)
def create_bucket():
    """Never reach a real S3 endpoint; the bucket is created unless a test sets a side effect."""
    with unittest.mock.patch("charm.create_bucket_if_not_exists") as create_bucket_if_not_exists:
        yield create_bucket_if_not_exists


@pytest.fixture(scope="function")
def context(temporal_k8s_charm):
    return ops.testing.Context(charm_type=temporal_k8s_charm)


@pytest.fixture(scope="function")
def log_dir_execs():
    return {
        ops.testing.Exec(["logrotate", "/etc/logrotate.d/temporal-server"]),
    }


@pytest.fixture(scope="function")
def temporal_container(log_dir_execs):
    return ops.testing.Container(
        "temporal",
        can_connect=True,
        execs=log_dir_execs,
    )


@pytest.fixture(scope="function")
def temporal_container_initialized(log_dir_execs):
    return ops.testing.Container(
        "temporal",
        can_connect=True,
        execs=log_dir_execs,
        check_infos=[ops.testing.CheckInfo("temporal-server-running")],
        layers={
            "initialized-layer": ops.pebble.Layer(
                {
                    "checks": {
                        "temporal-server-running": ops.pebble.CheckDict(
                            exec=ops.pebble.ExecDict(
                                command="temporal operator cluster health --address=temporal-k8s:7236",
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
def configured_container(temporal_container_initialized):
    """Return a builder of the container as the charm configured it."""

    def build(state_out, status, check_status=ops.pebble.CheckStatus.UP):
        """Build the container from the layers the charm planned.

        Args:
            state_out: The state after the charm planned the server.
            status: The status of the temporal-server service.
            check_status: The status of the temporal-server-running check.

        Returns:
            The container with the charm's layers and the service in the given status.
        """
        return dataclasses.replace(
            temporal_container_initialized,
            layers=state_out.get_container("temporal").layers,
            service_statuses={"temporal-server": status},
            check_infos=[
                ops.testing.CheckInfo(
                    "temporal-server-running",
                    level=ops.pebble.CheckLevel.ALIVE,
                    startup=ops.pebble.CheckStartup.UNSET,
                    status=check_status,
                    threshold=None,
                )
            ],
        )

    return build


@pytest.fixture(scope="function")
def incomplete_layer_dict():
    return {
        "services": {
            "temporal-server": {
                "override": "replace",
            },
        },
    }


@pytest.fixture(scope="function")
def temporal_container_incomplete_layer(incomplete_layer_dict, log_dir_execs):
    return ops.testing.Container(
        "temporal",
        can_connect=True,
        execs=log_dir_execs,
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
def s3_bucket_fingerprint(s3_config):
    return s3_fingerprint(s3_config)


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
def peer_relation(request, s3_config, openfga_store_id):
    """The peer databag holds only what the charm cannot read from a relation.

    That is the history shards, the OpenFGA authorization model, and the outcome of the S3 bucket
    creation. The database connections, the OpenFGA store and the S3 credentials come from their
    relations.
    """
    if request.node.get_closest_marker("peer_relation_skipped"):
        return ops.testing.Relation(endpoint="peer")

    state_data = {}

    if not request.node.get_closest_marker("config_skipped"):
        state_data["num_history_shards"] = "1"

    if not request.node.get_closest_marker("s3_relation_skipped"):
        state_data["s3_bucket"] = json.dumps({"fingerprint": s3_fingerprint(s3_config), "bucket_created": True})

    if not request.node.get_closest_marker("openfga_uninitialized"):
        state_data["openfga"] = json.dumps(
            {
                "store_id": openfga_store_id,
                "auth_model_id": None if request.node.get_closest_marker("openfga_auth_skipped") else "123",
            }
        )

    return ops.testing.PeerRelation(endpoint="peer", local_app_data=state_data)


@pytest.fixture(scope="function")
def admin_relation():
    return ops.testing.Relation(
        "admin", remote_app_data={"schema_status": "ready", "migrated_workload_version": "1.31.2"}
    )


@pytest.fixture(scope="function")
def frontend_certificates_relation():
    return ops.testing.Relation("frontend-certificates")


@pytest.fixture(scope="function")
def host_info_relation():
    return ops.testing.Relation("temporal-host-info")


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
