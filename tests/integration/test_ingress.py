# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.


"""Integration test: expose the Temporal frontend via ingress-configurator + HAProxy.

Validated topology (end-to-end TLS):

    temporal-k8s:ingress -> ingress-configurator:ingress   (k8s model)
    ingress-configurator:haproxy-route -> haproxy:haproxy-route   (cross-model)
    haproxy:receive-ca-certs <- self-signed-certificates:send-ca-cert   (frontend CA, cross-model)

The Temporal frontend is a gRPC (HTTP/2) server that terminates TLS itself
(`frontend-certificates`); the supported providers do not do plaintext HTTP/2 to
the backend, so the charm advertises the `https` scheme and HAProxy re-encrypts to
the frontend. HAProxy is a machine charm, so it runs on a separate (LXD) model and
is related across models.

This test needs a substrate with both a Kubernetes and a machine (LXD) controller;
`concierge.yaml` provisions exactly that.
"""

import json
import logging
import socket
import ssl
import subprocess
from pathlib import Path

import grpc
import pytest
import yaml
from grpc_health.v1 import health_pb2, health_pb2_grpc

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
APP_NAME = METADATA["name"]

TEMPORAL_ADMIN = "temporal-admin-k8s"
TEMPORAL_ADMIN_CHANNEL = "stable"
POSTGRESQL_K8S = "postgresql-k8s"
POSTGRESQL_K8S_CHANNEL = "14/stable"
INGRESS_CONFIGURATOR = "ingress-configurator"
INGRESS_CONFIGURATOR_CHANNEL = "latest/edge"
SELF_SIGNED = "self-signed-certificates"
SELF_SIGNED_CHANNEL = "latest/stable"
HAPROXY = "haproxy"
HAPROXY_CHANNEL = "2.8/edge"

MACHINE_MODEL = "haproxy"
HOSTNAME = "temporal-k8s.test"
FRONTEND_GRPC_SERVICE = "temporal.api.workflowservice.v1.WorkflowService"
IDLE_TIMEOUT = "30m"


def juju(*args: str, model: str | None = None) -> str:
    """Run a juju CLI command and return its stdout.

    Args:
        args: juju subcommand and arguments.
        model: optional fully-qualified `<controller>:<model>` to target with `-m`.

    Returns:
        The command's stdout.
    """
    cmd = ["juju", args[0]]
    if model:
        cmd += ["-m", model]
    cmd += list(args[1:])
    logger.info("running: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)  # noqa: S603
    return result.stdout


def _controller_by_cloud(*clouds: str) -> str:
    """Return the name of the bootstrapped controller backed by one of ``clouds``."""
    controllers = json.loads(juju("controllers", "--format", "json"))["controllers"]
    for name, info in controllers.items():
        if info.get("cloud") in clouds:
            return name
    raise RuntimeError(f"no controller found for clouds {clouds}; check concierge bootstrapped it")


def _unit_address(model: str, unit: str) -> str:
    """Return a unit's public address from ``juju status``."""
    status = json.loads(juju("status", "--format", "json", model=model))
    app = unit.split("/")[0]
    return status["applications"][app]["units"][unit]["public-address"]


def _server_certificate(address: str, port: int, server_hostname: str) -> bytes:
    """Fetch the certificate the endpoint presents for ``server_hostname``.

    Fetched over the wire (with SNI) and used as the trust root - the gRPC
    equivalent of ``curl -k`` against a self-signed endpoint.
    """
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    with socket.create_connection((address, port), timeout=30) as sock:
        with context.wrap_socket(sock, server_hostname=server_hostname) as tls_sock:
            der_cert = tls_sock.getpeercert(binary_form=True)
    return ssl.DER_cert_to_PEM_cert(der_cert).encode()


@pytest.fixture(scope="module")
def charm_path(pytestconfig) -> str:
    """Path to the packed charm (built with charmcraft if not supplied)."""
    supplied = pytestconfig.getoption("--charm-file", default=None)
    if supplied:
        return supplied
    subprocess.run(["charmcraft", "pack"], check=True)  # noqa: S603, S607
    return str(sorted(Path(".").glob(f"{APP_NAME}_*.charm"))[0])


@pytest.fixture(scope="module")
def topology(charm_path):
    """Deploy the full cross-model topology and tear the machine model down after."""
    k8s_ctrl = _controller_by_cloud("k8s", "microk8s")
    lxd_ctrl = _controller_by_cloud("localhost", "lxd")
    k8s_model = f"{k8s_ctrl}:testing"
    lxd_model = f"{lxd_ctrl}:{MACHINE_MODEL}"

    juju("add-model", "-c", k8s_ctrl, "testing")
    juju("add-model", "-c", lxd_ctrl, MACHINE_MODEL)

    resources = f"temporal-server-image={METADATA['resources']['temporal-server-image']['upstream-source']}"

    # --- Kubernetes model ---
    juju("deploy", charm_path, APP_NAME, "--resource", resources, "--config", "num-history-shards=2", model=k8s_model)
    juju("deploy", TEMPORAL_ADMIN, "--channel", TEMPORAL_ADMIN_CHANNEL, model=k8s_model)
    juju("deploy", POSTGRESQL_K8S, "--channel", POSTGRESQL_K8S_CHANNEL, "--trust", model=k8s_model)
    juju("deploy", SELF_SIGNED, "--channel", SELF_SIGNED_CHANNEL, model=k8s_model)
    juju("deploy", INGRESS_CONFIGURATOR, "--channel", INGRESS_CONFIGURATOR_CHANNEL, "--trust", model=k8s_model)

    juju("integrate", f"{APP_NAME}:db", f"{POSTGRESQL_K8S}:database", model=k8s_model)
    juju("integrate", f"{APP_NAME}:visibility", f"{POSTGRESQL_K8S}:database", model=k8s_model)
    juju("integrate", f"{APP_NAME}:admin", f"{TEMPORAL_ADMIN}:admin", model=k8s_model)
    # Frontend serves gRPC over TLS.
    juju("integrate", f"{APP_NAME}:frontend-certificates", f"{SELF_SIGNED}:certificates", model=k8s_model)
    # Workload -> ingress-configurator (backend spoken over TLS).
    juju("integrate", f"{APP_NAME}:ingress", f"{INGRESS_CONFIGURATOR}:ingress", model=k8s_model)
    juju("config", INGRESS_CONFIGURATOR, f"hostname={HOSTNAME}", "backend-protocol=https", model=k8s_model)

    # --- Machine model ---
    juju("deploy", HAPROXY, "--channel", HAPROXY_CHANNEL, model=lxd_model)
    juju("deploy", SELF_SIGNED, "--channel", SELF_SIGNED_CHANNEL, model=lxd_model)
    juju("integrate", f"{HAPROXY}:certificates", SELF_SIGNED, model=lxd_model)
    juju("config", HAPROXY, f"external-hostname={HOSTNAME}", model=lxd_model)

    # --- Cross-model: route + backend-CA trust ---
    juju("offer", "-c", lxd_ctrl, f"{MACHINE_MODEL}.{HAPROXY}:haproxy-route")
    juju("consume", f"{lxd_ctrl}:admin/{MACHINE_MODEL}.{HAPROXY}", "haproxy-cmr", model=k8s_model)
    juju("integrate", f"{INGRESS_CONFIGURATOR}:haproxy-route", "haproxy-cmr", model=k8s_model)

    juju("offer", "-c", k8s_ctrl, f"testing.{SELF_SIGNED}:send-ca-cert")
    juju("consume", f"{k8s_ctrl}:admin/testing.{SELF_SIGNED}", "frontend-ca", model=lxd_model)
    juju("integrate", f"{HAPROXY}:receive-ca-certs", "frontend-ca", model=lxd_model)

    # --- Wait for both models to settle ---
    juju("wait-for", "application", APP_NAME, "--query", 'status=="active"', "--timeout", IDLE_TIMEOUT, model=k8s_model)
    juju("wait-for", "application", HAPROXY, "--query", 'status=="active"', "--timeout", IDLE_TIMEOUT, model=lxd_model)

    yield {"k8s_model": k8s_model, "lxd_model": lxd_model, "lxd_ctrl": lxd_ctrl}

    juju("destroy-model", f"{lxd_ctrl}:{MACHINE_MODEL}", "--no-prompt", "--force", "--destroy-storage")


@pytest.mark.abort_on_fail
def test_grpc_over_tls(topology):
    """The Temporal frontend is reachable via gRPC over TLS through HAProxy."""
    haproxy_ip = _unit_address(topology["lxd_model"], f"{HAPROXY}/0")

    # Verified TLS: trust HAProxy's presented cert, and set SNI/authority to the
    # routing hostname so HAProxy's host-based route matches.
    root_certificate = _server_certificate(haproxy_ip, 443, HOSTNAME)
    credentials = grpc.ssl_channel_credentials(root_certificates=root_certificate)
    options = (
        ("grpc.ssl_target_name_override", HOSTNAME),
        ("grpc.default_authority", HOSTNAME),
    )

    with grpc.secure_channel(f"{haproxy_ip}:443", credentials, options=options) as channel:
        stub = health_pb2_grpc.HealthStub(channel)
        request = health_pb2.HealthCheckRequest(service=FRONTEND_GRPC_SERVICE)
        response = stub.Check(request, timeout=30)
        assert response.status == health_pb2.HealthCheckResponse.SERVING
