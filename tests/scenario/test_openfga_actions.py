# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Scenario tests for OpenFGA actions validation."""

import dataclasses
import json
import unittest.mock

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
    (
        "http_api_url",
        "expected_scheme",
        "expected_address",
        "expected_port",
        "expected_full_http_url",
    ),
    [
        (
            "https://openfga.example.com/",
            "https",
            "openfga.example.com",
            443,
            "https://openfga.example.com",
        ),
        (
            "http://openfga.example.com/",
            "http",
            "openfga.example.com",
            80,
            "http://openfga.example.com",
        ),
        (
            "https://openfga.example.com:8443/",
            "https",
            "openfga.example.com",
            8443,
            "https://openfga.example.com:8443",
        ),
        (
            "https://openfga.example.com/some-prefix/",
            "https",
            "openfga.example.com",
            443,
            "https://openfga.example.com/some-prefix",
        ),
    ],
)
def test_openfga_http_url_is_parsed_into_peer_state(
    context,
    action_state,
    openfga_data,
    admin_relation,
    http_api_url,
    expected_scheme,
    expected_address,
    expected_port,
    expected_full_http_url,
):
    """Parse the OpenFGA HTTP URL into peer state."""
    state = _with_openfga_http_url(
        action_state,
        openfga_data,
        http_api_url,
    )

    state = context.run(
        context.on.relation_changed(admin_relation),
        state,
    )

    openfga = state.get_relations("openfga")[0]
    state_out = context.run(
        context.on.relation_changed(openfga),
        state,
    )

    peer = state_out.get_relations("peer")[0]
    openfga_state = json.loads(peer.local_app_data["openfga"])

    assert openfga_state["scheme"] == expected_scheme
    assert openfga_state["address"] == expected_address
    assert openfga_state["port"] == expected_port
    assert openfga_state["full_http_url"] == expected_full_http_url
    assert state_out.unit_status == ops.BlockedStatus("missing openfga authorization model")


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


def _with_peer_openfga(state, openfga, extra_peer=None):
    """Return state with OpenFGA data written to the peer app databag."""
    peer = state.get_relations("peer")[0]
    local_app_data = {**peer.local_app_data, "openfga": json.dumps(openfga)}
    if extra_peer:
        local_app_data.update(extra_peer)
    relations = [rel for rel in state.relations if rel.endpoint != "peer"]
    relations.append(dataclasses.replace(peer, local_app_data=local_app_data))
    return dataclasses.replace(state, relations=relations)


def _with_openfga_http_url(state, openfga_data, http_api_url):
    """Return state with a custom OpenFGA HTTP API URL on the relation."""
    openfga_relation = ops.testing.Relation(
        "openfga",
        remote_app_data={
            "store_id": openfga_data["store_id"],
            "token_secret_id": openfga_data["token_secret_id"],
            "http_api_url": http_api_url,
            "grpc_api_url": openfga_data["grpc_api_url"],
        },
    )
    relations = [rel for rel in state.relations if rel.endpoint != "openfga"]
    relations.append(openfga_relation)
    return dataclasses.replace(state, relations=relations)


def _legacy_openfga_state(openfga_store_id, port=None):
    """Return OpenFGA peer state as written by older charm revisions."""
    return {
        "store_id": openfga_store_id,
        "token": "openfga_token",
        "address": "openfga.example.com",
        "port": port,
        "scheme": "https",
        "auth_model_id": "modelid123",
    }


@unittest.mock.patch("socket.gethostbyname", return_value="127.0.0.1")
def test_upgrade_charm_migrates_null_port_and_missing_full_http_url(
    mock_dns,
    context,
    action_state,
    openfga_data,
    openfga_store_id,
):
    """upgrade-charm backfills portless 1.31 peer state from the live OpenFGA URL."""
    state = _with_openfga_http_url(action_state, openfga_data, "https://openfga.example.com/")
    state = _with_peer_openfga(
        state,
        _legacy_openfga_state(openfga_store_id, port=None),
        extra_peer={"schema_ready": "true"},
    )

    state_out = context.run(context.on.upgrade_charm(), state)

    peer = state_out.get_relations("peer")[0]
    openfga_state = json.loads(peer.local_app_data["openfga"])
    assert openfga_state["port"] == 443
    assert openfga_state["full_http_url"] == "https://openfga.example.com"
    assert openfga_state["auth_model_id"] == "modelid123"
    assert "missing parameters ['port']" not in str(state_out.unit_status)


@unittest.mock.patch("socket.gethostbyname", return_value="127.0.0.1")
def test_upgrade_charm_backfills_full_http_url_when_port_is_present(
    mock_dns,
    context,
    action_state,
    openfga_data,
    openfga_store_id,
):
    """upgrade-charm still writes full_http_url when old peer state already has a port."""
    state = _with_openfga_http_url(action_state, openfga_data, "https://openfga.example.com:8443/")
    state = _with_peer_openfga(
        state,
        _legacy_openfga_state(openfga_store_id, port=8443),
        extra_peer={"schema_ready": "true"},
    )

    state_out = context.run(context.on.upgrade_charm(), state)

    peer = state_out.get_relations("peer")[0]
    openfga_state = json.loads(peer.local_app_data["openfga"])
    assert openfga_state["port"] == 8443
    assert openfga_state["full_http_url"] == "https://openfga.example.com:8443"
    assert openfga_state["auth_model_id"] == "modelid123"
    assert "missing parameters ['port']" not in str(state_out.unit_status)


@unittest.mock.patch("socket.gethostbyname", return_value="127.0.0.1")
def test_upgrade_charm_blocks_when_full_http_url_cannot_be_migrated(
    mock_dns,
    context,
    action_state,
    openfga_store_id,
):
    """Unrecoverable stale peer state blocks on missing full_http_url after upgrade."""
    relations = [rel for rel in action_state.relations if rel.endpoint != "openfga"]
    relations.append(ops.testing.Relation("openfga", remote_app_data={}))
    state = dataclasses.replace(action_state, relations=relations)
    state = _with_peer_openfga(
        state,
        _legacy_openfga_state(openfga_store_id, port=443),
        extra_peer={"schema_ready": "true"},
    )

    state_out = context.run(context.on.upgrade_charm(), state)

    assert state_out.unit_status == ops.BlockedStatus("openfga:missing parameters ['full_http_url']")


@pytest.mark.openfga_uninitialized
@pytest.mark.parametrize(
    "http_api_url",
    [
        "https:///foo",
        "https://openfga.example.com?foo=bar",
        "https://openfga.example.com/#foo",
        "ftp://openfga.example.com",
        "https://openfga.example.com:not-a-port",
    ],
)
def test_invalid_openfga_http_url_is_not_persisted_on_store_created(
    context,
    action_state,
    openfga_data,
    admin_relation,
    http_api_url,
):
    """Malformed OpenFGA HTTP URLs are rejected and not written to peer state."""
    state = _with_openfga_http_url(action_state, openfga_data, http_api_url)
    state = context.run(context.on.relation_changed(admin_relation), state)
    openfga = state.get_relations("openfga")[0]
    state_out = context.run(context.on.relation_changed(openfga), state)

    peer = state_out.get_relations("peer")[0]
    assert "openfga" not in peer.local_app_data
    assert isinstance(state_out.unit_status, ops.BlockedStatus)
    assert "openfga:temporal relation not ready" in str(state_out.unit_status)


@unittest.mock.patch("socket.gethostbyname", return_value="127.0.0.1")
def test_invalid_openfga_http_url_is_not_persisted_on_upgrade(
    mock_dns,
    context,
    action_state,
    openfga_data,
    openfga_store_id,
):
    """Upgrade does not overwrite existing peer OpenFGA state with an invalid URL."""
    legacy_openfga = _legacy_openfga_state(openfga_store_id, port=None)
    state = _with_openfga_http_url(action_state, openfga_data, "https://openfga.example.com?foo=bar")
    state = _with_peer_openfga(state, legacy_openfga, extra_peer={"schema_ready": "true"})

    state_out = context.run(context.on.upgrade_charm(), state)

    peer = state_out.get_relations("peer")[0]
    openfga_state = json.loads(peer.local_app_data["openfga"])

    assert openfga_state == legacy_openfga
    assert "full_http_url" not in openfga_state
    assert isinstance(state_out.unit_status, ops.BlockedStatus)
    assert "missing parameters" in str(state_out.unit_status)
