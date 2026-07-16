# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.


"""Temporal Server charm integration with the Gateway API.

Temporal's frontend is a gRPC (HTTP/2) server, so it is exposed through the
``ingress`` relation using host-based routing. The provider chain is:

    temporal-k8s:ingress
        -> ingress-configurator:ingress            (adds hostname + gRPC routing)
    ingress-configurator:gateway-route
        -> gateway-api-integrator:gateway-route     (creates Gateway + HTTPRoute)
    gateway-api-integrator:certificates
        -> self-signed-certificates:certificates    (TLS terminated at the gateway)

TLS is terminated at the gateway; the hop to the frontend is cleartext HTTP/2
(``h2c``), which is why the charm must NOT also enable ``frontend-certificates``.

Cluster prerequisites (Canonical Kubernetes):
    sudo k8s enable gateway        # provides the "ck-gateway" GatewayClass (Cilium)
    sudo k8s enable load-balancer  # assigns the Gateway an external IP
"""

import asyncio
import logging
import re
import socket
import ssl
from pathlib import Path

import grpc
import pytest
import pytest_asyncio
import yaml
from grpc_health.v1 import health_pb2, health_pb2_grpc
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
APP_NAME = METADATA["name"]

TEMPORAL_ADMIN = "temporal-admin-k8s"
TEMPORAL_ADMIN_CHANNEL = "stable"
POSTGRESQL_K8S = "postgresql-k8s"
POSTGRESQL_K8S_CHANNEL = "14"
POSTGRESQL_K8S_TRUST = True

GATEWAY_API_INTEGRATOR = "gateway-api-integrator"
GATEWAY_API_INTEGRATOR_CHANNEL = "latest/stable"
GATEWAY_API_INTEGRATOR_TRUST = True
INGRESS_CONFIGURATOR = "ingress-configurator"
INGRESS_CONFIGURATOR_CHANNEL = "latest/stable"
SELF_SIGNED_CERTIFICATES = "self-signed-certificates"
SELF_SIGNED_CERTIFICATES_CHANNEL = "latest/stable"

# GatewayClass provided by `k8s enable gateway` on Canonical Kubernetes. On a
# vanilla upstream Cilium install this is instead "cilium".
GATEWAY_CLASS = "ck-gateway"
# Hostname used for host-based routing to the Temporal frontend.
EXTERNAL_HOSTNAME = "temporal-k8s.test"
FRONTEND_GRPC_SERVICE = "temporal.api.workflowservice.v1.WorkflowService"


@pytest_asyncio.fixture(name="deploy", scope="module")
async def deploy(ops_test: OpsTest):
    """Deploy Temporal behind the Gateway API integrator and wait for it to settle."""
    # Deploy the Temporal stack and the Gateway API ingress chain.
    await asyncio.gather(
        ops_test.model.deploy(TEMPORAL_ADMIN, channel=TEMPORAL_ADMIN_CHANNEL),
        ops_test.model.deploy(POSTGRESQL_K8S, channel=POSTGRESQL_K8S_CHANNEL, trust=POSTGRESQL_K8S_TRUST),
        ops_test.model.deploy(
            GATEWAY_API_INTEGRATOR,
            channel=GATEWAY_API_INTEGRATOR_CHANNEL,
            trust=GATEWAY_API_INTEGRATOR_TRUST,
        ),
        ops_test.model.deploy(INGRESS_CONFIGURATOR, channel=INGRESS_CONFIGURATOR_CHANNEL),
        ops_test.model.deploy(SELF_SIGNED_CERTIFICATES, channel=SELF_SIGNED_CERTIFICATES_CHANNEL),
    )

    # Build and deploy temporal-k8s.
    charm = await ops_test.build_charm(".")
    resources = {"temporal-server-image": METADATA["resources"]["temporal-server-image"]["upstream-source"]}
    await ops_test.model.deploy(charm, resources=resources, application_name=APP_NAME, config={"num-history-shards": 2})

    # Configure the gateway and the route.
    await ops_test.model.applications[GATEWAY_API_INTEGRATOR].set_config(
        {"gateway-class": GATEWAY_CLASS, "external-hostname": EXTERNAL_HOSTNAME}
    )
    # Route the Temporal frontend by hostname. The gRPC frontend speaks cleartext
    # HTTP/2, so the backend protocol is plain HTTP (h2c) with TLS handled by the
    # gateway.
    await ops_test.model.applications[INGRESS_CONFIGURATOR].set_config(
        {"hostname": EXTERNAL_HOSTNAME, "backend-protocol": "http"}
    )

    async with ops_test.fast_forward():
        # Temporal core relations.
        await ops_test.model.integrate(f"{APP_NAME}:db", f"{POSTGRESQL_K8S}:database")
        await ops_test.model.integrate(f"{APP_NAME}:visibility", f"{POSTGRESQL_K8S}:database")
        await ops_test.model.integrate(f"{APP_NAME}:admin", f"{TEMPORAL_ADMIN}:admin")

        # Gateway API ingress chain.
        await ops_test.model.integrate(
            f"{SELF_SIGNED_CERTIFICATES}:certificates", f"{GATEWAY_API_INTEGRATOR}:certificates"
        )
        await ops_test.model.integrate(
            f"{INGRESS_CONFIGURATOR}:gateway-route", f"{GATEWAY_API_INTEGRATOR}:gateway-route"
        )
        await ops_test.model.integrate(f"{APP_NAME}:ingress", f"{INGRESS_CONFIGURATOR}:ingress")

        await ops_test.model.wait_for_idle(
            status="active",
            raise_on_blocked=False,
            timeout=90 * 10,
        )


@pytest.mark.abort_on_fail
@pytest.mark.usefixtures("deploy")
class TestDeployment:
    """Integration tests for Temporal Server exposed through the Gateway API."""

    async def gateway_address(self, ops_test: OpsTest) -> str:
        """Return the external IP address assigned to the Gateway.

        The gateway-api-integrator publishes it in its unit status message as
        ``Gateway addresses: <ip>``.

        Args:
          ops_test: PyTest object.

        Returns:
          The gateway's external IP address.
        """
        unit = ops_test.model.applications[GATEWAY_API_INTEGRATOR].units[0]
        message = unit.workload_status_message
        match = re.search(r"Gateway addresses:\s*(\S+)", message)
        assert match, f"gateway address not found in status message: {message!r}"
        return match.group(1).rstrip(",")

    def _server_certificate(self, address: str, port: int, server_hostname: str) -> bytes:
        """Fetch the certificate the gateway presents for ``server_hostname``.

        The certificate is issued by self-signed-certificates, so it is fetched
        over the wire (with SNI set to the routing hostname) and used as the
        trust root - the equivalent of ``curl -k`` for a gRPC channel.

        Args:
          address: The gateway IP address to connect to.
          port: The TLS port to connect to.
          server_hostname: The SNI/hostname to request.

        Returns:
          The PEM-encoded server certificate.
        """
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        with socket.create_connection((address, port), timeout=30) as sock:
            with context.wrap_socket(sock, server_hostname=server_hostname) as tls_sock:
                der_cert = tls_sock.getpeercert(binary_form=True)
        return ssl.DER_cert_to_PEM_cert(der_cert).encode()

    async def test_ingress(self, ops_test: OpsTest):
        """The Temporal frontend is reachable via gRPC through the gateway."""
        gateway_ip = await self.gateway_address(ops_test)

        # TLS is terminated at the gateway on 443; connect with SNI/authority set
        # to the routing hostname so the Gateway routes to the Temporal frontend.
        root_certificate = self._server_certificate(gateway_ip, 443, EXTERNAL_HOSTNAME)
        credentials = grpc.ssl_channel_credentials(root_certificates=root_certificate)
        options = (
            ("grpc.ssl_target_name_override", EXTERNAL_HOSTNAME),
            ("grpc.default_authority", EXTERNAL_HOSTNAME),
        )

        # A healthy Frontend service replies with status SERVING.
        with grpc.secure_channel(f"{gateway_ip}:443", credentials, options=options) as channel:
            stub = health_pb2_grpc.HealthStub(channel)
            request = health_pb2.HealthCheckRequest(service=FRONTEND_GRPC_SERVICE)
            response = stub.Check(request, timeout=30)
            assert response.status == health_pb2.HealthCheckResponse.SERVING
