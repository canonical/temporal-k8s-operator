#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Temporal charm integration tests."""

import json
import logging
import time

import pytest
from conftest import deploy  # noqa: F401, pylint: disable=W0611
from helpers import APP_NAME, run_sample_workflow
from juju.action import Action
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)


@pytest.mark.abort_on_fail
@pytest.mark.usefixtures("deploy")
class TestAuth:
    """Integration tests for Temporal charm."""

    async def test_openfga_relation(self, ops_test: OpsTest):
        """Add OpenFGA relation and authorization model."""
        await ops_test.model.applications[APP_NAME].set_config({"auth-enabled": "true"})
        await ops_test.model.deploy("openfga-k8s", channel="latest/edge")
        await ops_test.model.wait_for_idle(
            apps=[APP_NAME, "openfga-k8s"],
            status="blocked",
            raise_on_blocked=False,
            timeout=1200,
        )

        logger.info("adding openfga postgresql relation")
        await ops_test.model.integrate("openfga-k8s:database", "postgresql-k8s:database")

        await ops_test.model.wait_for_idle(
            apps=["openfga-k8s"],
            status="blocked",
            raise_on_blocked=False,
            timeout=1200,
        )

        openfga_unit = ops_test.model.applications["openfga-k8s"].units[0]
        for i in range(10):
            action: Action = await openfga_unit.run_action("schema-upgrade")
            result = await action.wait()
            logger.info(f"attempt {i} -> action result {result.status} {result.results}")
            if result.results == {"result": "done", "return-code": 0}:
                break
            time.sleep(2)

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
        with open("./tests/integration/authorization_model.json", "r", encoding="utf-8") as model_file:
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
                if result.status == "completed" and result.results == {"return-code": 0}:
                    break
                time.sleep(2)

        await ops_test.model.wait_for_idle(
            apps=[APP_NAME],
            status="active",
            raise_on_blocked=True,
            timeout=300,
        )

        assert ops_test.model.applications[APP_NAME].status == "active"

        await run_sample_workflow(ops_test)

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