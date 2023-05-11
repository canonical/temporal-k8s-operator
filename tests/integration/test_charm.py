# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Temporal charm integration tests."""

import logging

import pytest
from conftest import deploy  # noqa: F401, pylint: disable=W0611
from helpers import run_sample_workflow
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)


@pytest.mark.abort_on_fail
@pytest.mark.usefixtures("deploy")
class TestDeployment:
    """Integration tests for Temporal charm."""

    async def test_basic_client(self, ops_test: OpsTest):
        """Connects a client and runs a basic Temporal workflow."""
        await run_sample_workflow(ops_test)
