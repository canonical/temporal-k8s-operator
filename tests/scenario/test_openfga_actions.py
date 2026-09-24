# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Scenario tests for OpenFGA actions validation."""

import dataclasses
import json
import unittest.mock
from urllib.parse import urlsplit

import ops
import ops.testing
import pytest
from relations.openfga import _get_ofga_client


@pytest.fixture
def action_state(
    temporal_container,
    peer_relation,
    admin_relation,
    db_relation,
    visibility_relation,
    nginx_route_relation,
    openfga_relation,
    s3_relation,
    network,
    openfga_secret,
):
    return ops.testing.State(
        leader=True,
        containers=[temporal_container],
        config={"num-history-shards": 1, "auth-enabled": True},
        relations=[
            peer_relation,
            admin_relation,
            db_relation,
            visibility_relation,
            nginx_route_relation,
            openfga_relation,
            s3_relation,
        ],
        networks=[network],
        secrets=[openfga_secret],
    )


class TestListAuthRuleActionValidation:
    """Tests for list-auth-rule action input validation."""

    @unittest.mock.patch("socket.gethostbyname", return_value="127.0.0.1")
    def test_list_auth_rule_fails_with_empty_namespace(self, mock_dns, context, action_state):
        with pytest.raises(ops.testing.ActionFailed) as exc_info:
            context.run(context.on.action("list-auth-rule", params={"namespace": ""}), action_state)

        assert "namespace" in str(exc_info.value).lower() or "empty" in str(exc_info.value).lower()

    @unittest.mock.patch("socket.gethostbyname", return_value="127.0.0.1")
    def test_list_auth_rule_fails_with_empty_user(self, mock_dns, context, action_state):
        with pytest.raises(ops.testing.ActionFailed) as exc_info:
            context.run(context.on.action("list-auth-rule", params={"user": ""}), action_state)

        assert "user" in str(exc_info.value).lower() or "empty" in str(exc_info.value).lower()

    @unittest.mock.patch("socket.gethostbyname", return_value="127.0.0.1")
    def test_list_auth_rule_fails_with_empty_group(self, mock_dns, context, action_state):
        with pytest.raises(ops.testing.ActionFailed) as exc_info:
            context.run(context.on.action("list-auth-rule", params={"group": ""}), action_state)

        assert "group" in str(exc_info.value).lower() or "empty" in str(exc_info.value).lower()


@pytest.mark.openfga_uninitialized
@pytest.mark.parametrize(
    "http_api_url, expected_port",
    [
        ("https://openfga.example.com/", 443),
        ("http://openfga.example.com/", 80),
        ("https://openfga.example.com:8443/", 8443),
    ],
)
def test_portless_https_openfga_url(
    context,
    action_state,
    openfga_data,
    admin_relation,
    http_api_url,
    expected_port,
):
    """Parse portless and explicit OpenFGA URLs from relation data into peer state."""
    openfga_relation = ops.testing.Relation(
        "openfga",
        remote_app_data={
            "store_id": openfga_data["store_id"],
            "token_secret_id": openfga_data["token_secret_id"],
            "http_api_url": http_api_url,
            "grpc_api_url": openfga_data["grpc_api_url"],
        },
    )
    relations = [rel for rel in action_state.relations if rel.endpoint != "openfga"]
    relations.append(openfga_relation)
    state = dataclasses.replace(action_state, relations=relations)

    # Admin schema is validated before OpenFGA; process it so the missing-model
    # status is reachable instead of "schema is not ready".
    state = context.run(context.on.relation_changed(admin_relation), state)
    openfga = state.get_relations("openfga")[0]
    state_out = context.run(context.on.relation_changed(openfga), state)

    peer = state_out.get_relations("peer")[0]
    openfga_state = json.loads(peer.local_app_data["openfga"])
    parsed = urlsplit(http_api_url)

    assert openfga_state["scheme"] == parsed.scheme
    assert openfga_state["address"] == "openfga.example.com"
    assert openfga_state["port"] == expected_port
    assert openfga_state["full_http_url"] == http_api_url.rstrip("/")
    assert state_out.unit_status == ops.BlockedStatus("missing openfga authorization model")
    assert "missing parameters ['port']" not in str(state_out.unit_status)


def test_create_authorization_model_posts_full_http_url(context, action_state, openfga_store_id):
    """create-authorization-model POSTs full_http_url, including a path prefix."""
    peer = action_state.get_relations("peer")[0]
    openfga = json.loads(peer.local_app_data["openfga"])
    openfga.update(
        {
            "address": "127.0.0.1",
            "port": 8080,
            "scheme": "http",
            "full_http_url": "https://openfga.example.com/some-prefix",
            "auth_model_id": None,
        }
    )
    relations = [rel for rel in action_state.relations if rel.endpoint != "peer"]
    relations.append(
        dataclasses.replace(
            peer,
            local_app_data={**peer.local_app_data, "openfga": json.dumps(openfga)},
        )
    )
    state = dataclasses.replace(action_state, relations=relations)

    mock_response = unittest.mock.MagicMock()
    mock_response.ok = True
    mock_response.json.return_value = {"authorization_model_id": "modelid123"}

    with unittest.mock.patch("relations.openfga.requests.post", return_value=mock_response) as mock_post:
        context.run(
            context.on.action(
                "create-authorization-model",
                params={"model": json.dumps({"type_definitions": []})},
            ),
            state,
        )

    mock_post.assert_called_once()
    assert mock_post.call_args.args[0] == (
        f"https://openfga.example.com/some-prefix/stores/{openfga_store_id}/authorization-models"
    )


def test_get_ofga_client_uses_full_http_url():
    """_get_ofga_client configures the SDK with api_url, not reconstructed host/scheme."""
    openfga_data = {
        "store_id": "storeid12345",
        "token": "openfga_token",
        "address": "127.0.0.1",
        "port": 8080,
        "scheme": "http",
        "full_http_url": "https://openfga.example.com/some-prefix",
        "auth_model_id": "modelid123",
    }

    with unittest.mock.patch("relations.openfga.ClientConfiguration") as mock_config, unittest.mock.patch(
        "relations.openfga.OpenFgaClient"
    ):
        _get_ofga_client(openfga_data)

    mock_config.assert_called_once()
    kwargs = mock_config.call_args.kwargs
    assert kwargs["api_url"] == "https://openfga.example.com/some-prefix"
    assert "api_scheme" not in kwargs
    assert "api_host" not in kwargs
    assert kwargs["store_id"] == "storeid12345"
    assert kwargs["authorization_model_id"] == "modelid123"
