# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Scenario tests for OpenFGA actions validation."""

import unittest.mock

import ops.testing
import pytest


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
