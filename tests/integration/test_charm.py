#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd Ltd.
# See LICENSE file for licensing details.


import logging
from pathlib import Path

import pytest
import yaml
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
APP_NAME = METADATA["name"]


@pytest.fixture(name="deploy", scope="module")
async def deploy(ops_test: OpsTest):
    charm = await ops_test.build_charm(".")
    resources = {"temporal-server-image": METADATA["resources"]["temporal-server-image"]["upstream-source"]}
    await ops_test.model.deploy(charm, resources=resources, application_name=APP_NAME)
    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(apps=[APP_NAME], status="blocked", raise_on_blocked=False, timeout=1000)
        assert ops_test.model.applications[APP_NAME].units[0].workload_status == "active"


@pytest.mark.abort_on_fail
@pytest.mark.usefixtures("deploy")
class TestDeployment:
    async def test_application_is_up(self, ops_test: OpsTest):
        """The app is up and running."""
        # TODO(frankban): do something like the following.

        # import urllib.request

        # status = await ops_test.model.get_status()  # noqa: F821
        # address = status["applications"][APP_NAME]["units"][f"{APP_NAME}/0"]["address"]

        # url = f"http://{address}"
        # logger.info("querying app address: %s", url)
        # response = urllib.request.urlopen(url, data=None, timeout=2.0)
        # assert response.code == 200
