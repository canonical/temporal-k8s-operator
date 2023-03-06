#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd Ltd.
# See LICENSE file for licensing details.

import logging
from multiprocessing import Process
from pathlib import Path

import pytest
import pytest_asyncio
import yaml
from pytest_operator.plugin import OpsTest
from temporal_client.run_worker import sync_run_worker
from temporal_client.run_workflow import run_workflow

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
APP_NAME = METADATA["name"]

METADATA_ADMIN = yaml.safe_load(Path("../temporal-admin-k8s-operator/metadata.yaml").read_text())
APP_NAME_ADMIN = METADATA_ADMIN["name"]


@pytest_asyncio.fixture(name="deploy", scope="module")
async def deploy(ops_test: OpsTest):
    """The app is up and running."""
    charm = await ops_test.build_charm(".")
    resources = {"temporal-server-image": METADATA["containers"]["temporal"]["upstream-source"]}

    admin_resources = {"temporal-admin-image": METADATA_ADMIN["containers"]["temporal-admin"]["upstream-source"]}
    admin_charm = await ops_test.build_charm("../temporal-admin-k8s-operator")

    # Deploy temporal server, temporal admin and postgresql charms
    await ops_test.model.deploy(charm, resources=resources, application_name=APP_NAME)
    await ops_test.model.deploy(admin_charm, resources=admin_resources, application_name=APP_NAME_ADMIN)
    await ops_test.model.deploy("postgresql-k8s", channel="edge", trust=True)

    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(
            apps=[APP_NAME, APP_NAME_ADMIN], status="blocked", raise_on_blocked=False, timeout=600
        )
        await ops_test.model.wait_for_idle(
            apps=["postgresql-k8s"], status="active", raise_on_blocked=False, timeout=600
        )

        await ops_test.model.relate(f"{APP_NAME}:db", "postgresql-k8s:db")
        await ops_test.model.relate(f"{APP_NAME}:visibility", "postgresql-k8s:db")
        await ops_test.model.relate(f"{APP_NAME}:admin", f"{APP_NAME_ADMIN}:admin")

        await ops_test.model.wait_for_idle(apps=[APP_NAME], status="active", raise_on_blocked=False, timeout=600)

        action = (
            await ops_test.model.applications[APP_NAME_ADMIN]
            .units[0]
            .run_action("tctl", args="--ns default namespace register -rd 3")
        )
        result = (await action.wait()).results

        logger.info(f"tctl result: {result}")

        await ops_test.model.wait_for_idle(apps=[APP_NAME], status="active", raise_on_blocked=False, timeout=600)

        assert ops_test.model.applications[APP_NAME].units[0].workload_status == "active"


@pytest.mark.abort_on_fail
@pytest.mark.usefixtures("deploy")
class TestDeployment:
    async def test_basic_client(self, ops_test: OpsTest):

        status = await ops_test.model.get_status()  # noqa: F821
        address = status["applications"][APP_NAME]["units"][f"{APP_NAME}/0"]["address"]

        url = f"{address}:7233"
        logger.info("running workflow on app address: %s", url)

        t = Process(target=sync_run_worker, args=[url])
        t.start()

        logger.info("temporal worker running")

        name = "Jean-luc"
        result = await run_workflow(url, name)

        t.terminate()

        assert result == f"Hello, {name}!"
