#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Temporal charm integration tests."""

import logging

import pytest
import requests
from conftest import deploy  # noqa: F401, pylint: disable=W0611
from helpers import APP_NAME_UI, get_unit_url, run_sample_workflow, run_signal_workflow
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)


@pytest.mark.abort_on_fail
@pytest.mark.usefixtures("deploy")
class TestDeployment:
    """Integration tests for Temporal charm."""

    async def test_ui_relation(self, ops_test: OpsTest):
        """Perform GET request on the Temporal UI host."""
        url = await get_unit_url(ops_test, application=APP_NAME_UI, unit=0, port=8080)
        logger.info("curling app address: %s", url)

        response = requests.get(url, timeout=300)
        assert response.status_code == 200

    async def test_basic_client(self, ops_test: OpsTest):
        """Connects a client and runs a basic Temporal workflow."""
        await run_sample_workflow(ops_test)

    async def test_charm_crash(self, ops_test: OpsTest):
        """Test backup and restore functionality.

        This tests the charm's ability to continue workflow execution after simulating
        a crash in the charm. Essentially, it should prove that the charm is stateless
        and relies only on the db to store its workflow execution status.
        """
        await run_signal_workflow(ops_test)
