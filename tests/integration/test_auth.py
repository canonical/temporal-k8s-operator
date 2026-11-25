#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Temporal charm integration tests."""

import logging

import jubilant
import pytest
from conftest import deploy  # noqa: F401, pylint: disable=W0611
from helpers import (
    APP_NAME,
    DENIED,
    create_authorization_model,
    fast_forward,
    perform_add_auth_rule_action,
    perform_check_auth_rule_action,
    perform_list_auth_rule_action,
    perform_list_system_admins_action,
    perform_remove_auth_rule_action,
    probe,
    scale,
    unit_frontend,
    wait_active,
    wait_blocked,
)

logger = logging.getLogger(__name__)


@pytest.mark.abort_on_fail
@pytest.mark.usefixtures("deploy")
class TestAuth:
    """Integration tests for Temporal charm."""

    def test_openfga_relation(self, juju: jubilant.Juju):
        """Add OpenFGA relation and authorization model."""
        juju.model_config({"update-status-hook-interval": "1m"})

        juju.config(APP_NAME, {"auth-enabled": "true", "auth-admin-groups": "red,green"})
        juju.deploy("openfga-k8s", channel="2.0/stable")

        with fast_forward(juju):
            juju.wait(
                lambda status: jubilant.all_blocked(status, APP_NAME)
                and jubilant.all_agents_idle(status, APP_NAME, "openfga-k8s"),
                error=jubilant.any_error,
                timeout=1200,
            )

            logger.info("adding openfga postgresql relation")
            juju.integrate("openfga-k8s:database", "postgresql-k8s:database")

            wait_active(juju, "openfga-k8s", timeout=1200)

            logger.info("adding openfga relation")
            juju.integrate(APP_NAME, "openfga-k8s")

            wait_blocked(juju, APP_NAME, timeout=600)

            logger.info("running the create authorization model action")
            create_authorization_model(juju)

            wait_active(juju, APP_NAME, timeout=600, error=lambda status: jubilant.any_blocked(status, APP_NAME))

            assert juju.status().apps[APP_NAME].is_active

            # Anonymous requests to the public frontend must be rejected.
            assert probe(unit_frontend(juju, f"{APP_NAME}/0"), "default", "list") == DENIED

    def test_openfga_add_auth_rule_action(self, juju: jubilant.Juju):
        """Test add-auth-rule action."""
        perform_add_auth_rule_action(juju, user="test@example.com", group="test_group")
        perform_add_auth_rule_action(juju, group="test_group", namespace="test_namespace", role="reader")

    def test_openfga_check_auth_rule_action(self, juju: jubilant.Juju):
        """Test check-auth-rule action."""
        perform_check_auth_rule_action(juju, exp_result=True, user="test@example.com", group="test_group")
        perform_check_auth_rule_action(juju, exp_result=False, user="faker@example.com", group="test_group")
        perform_check_auth_rule_action(
            juju, exp_result=True, group="test_group", namespace="test_namespace", role="reader"
        )

    def test_openfga_list_auth_rule_action(self, juju: jubilant.Juju):
        """Test list-auth-rule action."""
        perform_list_auth_rule_action(juju, user="test@example.com")
        perform_list_auth_rule_action(juju, group="test_group")
        perform_list_auth_rule_action(juju, namespace="test_namespace")

    def test_openfga_list_system_admins_action(self, juju: jubilant.Juju):
        """Test list-auth-rule action."""
        perform_add_auth_rule_action(juju, user="admin_one@example.com", group="red")
        perform_add_auth_rule_action(juju, user="admin_two@example.com", group="green")
        perform_list_system_admins_action(juju)

    def test_openfga_remove_auth_rule_action(self, juju: jubilant.Juju):
        """Test remove-auth-rule action."""
        perform_remove_auth_rule_action(juju, group="test_group", namespace="test_namespace", role="reader")
        perform_check_auth_rule_action(
            juju, exp_result=False, group="test_group", namespace="test_namespace", role="reader"
        )

        perform_remove_auth_rule_action(juju, user="test@example.com", group="test_group")
        perform_check_auth_rule_action(juju, exp_result=False, user="test@example.com", group="test_group")

    def test_scaling_auth(self, juju: jubilant.Juju):
        """Scale Temporal server to 2 units and test active status."""
        scale(juju, app=APP_NAME, units=2)

    def test_openfga_relation_removed(self, juju: jubilant.Juju):
        """Remove OpenFGA relation."""
        juju.remove_relation(f"{APP_NAME}:openfga", "openfga-k8s:openfga")

        wait_blocked(juju, APP_NAME, timeout=600)

        assert juju.status().apps[APP_NAME].is_blocked
