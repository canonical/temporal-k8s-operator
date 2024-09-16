#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Temporal charm integration tests."""

import json
import logging
import time

import pytest
from conftest import deploy  # noqa: F401, pylint: disable=W0611
from helpers import (
    APP_NAME,
    perform_add_auth_rule_action,
    perform_check_auth_rule_action,
    perform_list_auth_rule_action,
    perform_list_system_admins_action,
    perform_remove_auth_rule_action,
    run_sample_workflow,
    scale,
)
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)


@pytest.mark.abort_on_fail
@pytest.mark.usefixtures("deploy")
class TestAuth:
    """Integration tests for Temporal charm."""

    async def test_openfga_relation(self, ops_test: OpsTest):
        """Add OpenFGA relation and authorization model."""
        await ops_test.model.set_config({"update-status-hook-interval": "1m"})

        await ops_test.model.applications[APP_NAME].set_config(
            {"auth-enabled": "true", "auth-admin-groups": "red,green"}
        )
        await ops_test.model.deploy("openfga-k8s", channel="2.0/stable")

        async with ops_test.fast_forward():
            await ops_test.model.wait_for_idle(
                apps=[APP_NAME, "openfga-k8s"],
                status="blocked",
                raise_on_blocked=False,
                raise_on_error=False,
                timeout=1200,
            )

            logger.info("adding openfga postgresql relation")
            await ops_test.model.integrate("openfga-k8s:database", "postgresql-k8s:database")

            await ops_test.model.wait_for_idle(
                apps=["openfga-k8s"],
                status="active",
                raise_on_blocked=False,
                timeout=1200,
            )

            logger.info("adding openfga relation")
            await ops_test.model.integrate(APP_NAME, "openfga-k8s")

            await ops_test.model.wait_for_idle(
                apps=[APP_NAME],
                status="blocked",
                raise_on_blocked=False,
                timeout=600,
            )

            logger.info("running the create authorization model action")
            temporal_unit = ops_test.model.applications[APP_NAME].units[0]
            with open("./temporal_auth_model.json", "r", encoding="utf-8") as model_file:
                model_data = model_file.read()

                # Remove whitespace and newlines from JSON object
                json_text = "".join(model_data.split())
                data = json.loads(json_text)
                model_data = json.dumps(data, separators=(",", ":"))

                for i in range(10):
                    action = await temporal_unit.run_action(
                        "create-authorization-model",
                        model=model_data,
                    )
                    result = await action.wait()
                    logger.info(f"attempt {i} -> action result {result.status} {result.results}")
                    if result.status == "completed" and result.results == {
                        "result": "successfully created authorization model",
                        "return-code": 0,
                    }:
                        break
                    time.sleep(2)

            await ops_test.model.wait_for_idle(
                apps=[APP_NAME],
                status="active",
                raise_on_blocked=True,
                timeout=600,
            )

            assert ops_test.model.applications[APP_NAME].status == "active"

            try:
                await run_sample_workflow(ops_test)
            except RuntimeError as e:
                assert "Request unauthorized." in str(e)

    async def test_openfga_add_auth_rule_action(self, ops_test: OpsTest):
        """Test add-auth-rule action."""
        await perform_add_auth_rule_action(ops_test, user="test@example.com", group="test_group")
        await perform_add_auth_rule_action(ops_test, group="test_group", namespace="test_namespace", role="reader")

    async def test_openfga_check_auth_rule_action(self, ops_test: OpsTest):
        """Test check-auth-rule action."""
        await perform_check_auth_rule_action(ops_test, exp_result=True, user="test@example.com", group="test_group")
        await perform_check_auth_rule_action(ops_test, exp_result=False, user="faker@example.com", group="test_group")
        await perform_check_auth_rule_action(
            ops_test, exp_result=True, group="test_group", namespace="test_namespace", role="reader"
        )

    async def test_openfga_list_auth_rule_action(self, ops_test: OpsTest):
        """Test list-auth-rule action."""
        await perform_list_auth_rule_action(ops_test, user="test@example.com")
        await perform_list_auth_rule_action(ops_test, group="test_group")
        await perform_list_auth_rule_action(ops_test, namespace="test_namespace")

    async def test_openfga_list_system_admins_action(self, ops_test: OpsTest):
        """Test list-auth-rule action."""
        await perform_add_auth_rule_action(ops_test, user="admin_one@example.com", group="red")
        await perform_add_auth_rule_action(ops_test, user="admin_two@example.com", group="green")
        await perform_list_system_admins_action(ops_test)

    async def test_openfga_remove_auth_rule_action(self, ops_test: OpsTest):
        """Test remove-auth-rule action."""
        await perform_remove_auth_rule_action(ops_test, group="test_group", namespace="test_namespace", role="reader")
        await perform_check_auth_rule_action(
            ops_test, exp_result=False, group="test_group", namespace="test_namespace", role="reader"
        )

        await perform_remove_auth_rule_action(ops_test, user="test@example.com", group="test_group")
        await perform_check_auth_rule_action(ops_test, exp_result=False, user="test@example.com", group="test_group")

    async def test_scaling_auth(self, ops_test: OpsTest):
        """Scale Temporal server to 2 units and test active status."""
        await scale(ops_test, app=APP_NAME, units=2)

    async def test_openfga_relation_removed(self, ops_test: OpsTest):
        """Remove OpenFGA relation."""
        await ops_test.model.applications[APP_NAME].remove_relation(f"{APP_NAME}:openfga", "openfga-k8s:openfga")

        await ops_test.model.wait_for_idle(
            apps=[APP_NAME],
            status="blocked",
            raise_on_blocked=False,
            timeout=600,
        )

        assert ops_test.model.applications[APP_NAME].status == "blocked"
