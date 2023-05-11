#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd Ltd.
# See LICENSE file for licensing details.

"""Temporal charm integration test helpers."""

import logging
from multiprocessing import Process
from pathlib import Path

import yaml
from pytest_operator.plugin import OpsTest
from temporal_client.run_worker import sync_run_worker
from temporal_client.trigger_workflow import trigger_workflow

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
APP_NAME = METADATA["name"]
APP_NAME_ADMIN = "temporal-admin-k8s"


async def run_sample_workflow(ops_test: OpsTest):
    """Connects a client and runs a basic Temporal workflow.

    Args:
        ops_test: PyTest object.
    """
    status = await ops_test.model.get_status()  # noqa: F821
    address = status["applications"][APP_NAME].public_address
    url = f"{address}:7233"
    logger.info("running workflow on app address: %s", url)

    p = Process(target=sync_run_worker, args=[url])
    p.start()
    logger.info("temporal worker running")
    name = "Jean-luc"
    result = await trigger_workflow(url, name)
    p.terminate()

    assert result == f"Hello, {name}!"
