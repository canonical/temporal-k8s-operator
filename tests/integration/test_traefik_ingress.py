# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.


"""Temporal Server charm integration with Traefik tests."""

import asyncio
import json
import logging
from pathlib import Path

import grpc
import pytest
import pytest_asyncio
import yaml
from grpc_health.v1 import health_pb2, health_pb2_grpc
from ops import Application
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
APP_NAME = METADATA["name"]

TEMPORAL_ADMIN = "temporal-admin-k8s"
TEMPORAL_ADMIN_CHANNEL = "stable"
POSTGRESQL_K8S = "postgresql-k8s"
POSTGRESQL_K8S_CHANNEL = "14"
POSTGRESQL_K8S_TRUST = True
TRAEFIK_K8S = "traefik-k8s"
TRAEFIK_K8S_CHANNEL = "latest/stable"
TRAEFIK_K8S_TRUST = True


@pytest_asyncio.fixture(name="deploy", scope="module")
async def deploy(ops_test: OpsTest):
    """The app is up and running."""
    # Deploy temporal server, temporal admin, traefik-k8s, and postgresql charms.
    asyncio.gather(
        ops_test.model.deploy(TEMPORAL_ADMIN, channel=TEMPORAL_ADMIN_CHANNEL),
        ops_test.model.deploy(POSTGRESQL_K8S, channel=POSTGRESQL_K8S_CHANNEL, trust=POSTGRESQL_K8S_TRUST),
        ops_test.model.deploy(TRAEFIK_K8S, channel=TRAEFIK_K8S_CHANNEL, trust=TRAEFIK_K8S_TRUST),
    )

    # Build and deploy temporal-k8s
    charm = await ops_test.build_charm(".")
    resources = {"temporal-server-image": METADATA["resources"]["temporal-server-image"]["upstream-source"]}

    await ops_test.model.deploy(charm, resources=resources, application_name=APP_NAME, config={"num-history-shards": 2})

    # Add relations to temporal-ui-k8s
    async with ops_test.fast_forward():
        await ops_test.model.integrate(f"{APP_NAME}:db", f"{POSTGRESQL_K8S}:database")
        await ops_test.model.integrate(f"{APP_NAME}:visibility", f"{POSTGRESQL_K8S}:database")
        await ops_test.model.integrate(f"{APP_NAME}:admin", f"{TEMPORAL_ADMIN}:admin")
        await ops_test.model.integrate(f"{APP_NAME}:ingress", f"{TRAEFIK_K8S}:ingress")

        await ops_test.model.wait_for_idle(
            status="active",
            raise_on_blocked=False,
            timeout=90 * 10,
        )


@pytest.mark.abort_on_fail
@pytest.mark.usefixtures("deploy")
class TestDeployment:
    """Integration tests for Temporal Server charm as a requirer of ingress."""

    async def clean_endpoint(self, endpoint: str, traefik_app: Application) -> str:
        """Return a DNS name without prefixes or suffixes given a desired proxied-endpoint.

        Args:
          endpoint: The proxied-endpoint to clean.
          traefik_app: the Traefik application.

        Returns:
          endpoint: a DNS name without prefixes.
        """
        show_proxied_endpoints = await traefik_app.units[0].run_action("show-proxied-endpoints")
        await show_proxied_endpoints.wait()

        # Get LB IP address from proxied endpoints
        endpoint = json.loads(show_proxied_endpoints.results.get("proxied-endpoints")).get(endpoint).get("url")

        # Remove http and / from the endpoint
        return endpoint[len("http://") :].rstrip("/")  # noqa

    async def test_ingress(self, ops_test: OpsTest):
        """Test connectivity through ingress."""
        # Get the traefik-k8s app
        traefik_app = ops_test.model.applications.get(TRAEFIK_K8S)

        # Get the IP of the Loadbalancer from the proxied-endpoints
        loadbalancer_ip = await self.clean_endpoint(TRAEFIK_K8S, traefik_app)

        # Change traefik-k8s configuration to host based routing
        # This is required for the gRPC server that is Temporal frontend
        await traefik_app.set_config({"routing_mode": "subdomain", "external_hostname": f"{loadbalancer_ip}.nip.io"})

        await ops_test.model.wait_for_idle(
            apps=[TRAEFIK_K8S],
            status="active",
            raise_on_blocked=False,
            timeout=90 * 10,
        )

        # Get the Temporal Server clean endpoint
        temporal_server_endpoint = await self.clean_endpoint(APP_NAME, traefik_app)

        # Create a gRPC connection to the temporal.api.workflowservice.v1.WorkflowService API
        # A healthy Frontend service would reply with a status: SERVING
        with grpc.insecure_channel(f"{temporal_server_endpoint}:80") as channel:
            stub = health_pb2_grpc.HealthStub(channel)
            request = health_pb2.HealthCheckRequest(service="temporal.api.workflowservice.v1.WorkflowService")
            response = stub.Check(request, timeout=10)
            assert response.status == health_pb2.HealthCheckResponse.SERVING
