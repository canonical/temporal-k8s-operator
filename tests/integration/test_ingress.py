# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.
#
# The integration tests use the Jubilant library. See https://documentation.ubuntu.com/jubilant/
# To learn more about testing, see https://documentation.ubuntu.com/ops/latest/explanation/testing/

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
import sys
import time
from pathlib import Path

import grpc
import jubilant
import pytest
import yaml
from conftest import (
    POSTGRESQL_CHANNEL,
    SELF_SIGNED_CERTIFICATES_CHANNEL,
    TEMPORAL_CHANNEL,
)
from grpc_health.v1 import health_pb2, health_pb2_grpc

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
APP_NAME = METADATA["name"]

# temporal-admin-k8s must track the temporal-server image version (schema
# versions are tied to the server): `TEMPORAL_CHANNEL` (from conftest) matches
# the image in metadata.yaml. Reuse conftest's channels so there's a single
# source of truth shared with the ops_test suite.
TEMPORAL_ADMIN = "temporal-admin-k8s"
POSTGRESQL_K8S = "postgresql-k8s"
INGRESS_CONFIGURATOR = "ingress-configurator"
INGRESS_CONFIGURATOR_CHANNEL = "latest/edge"
SELF_SIGNED = "self-signed-certificates"
HAPROXY = "haproxy"
HAPROXY_CHANNEL = "2.8/edge"

HOSTNAME = "temporal-k8s.test"
FRONTEND_GRPC_SERVICE = "temporal.api.workflowservice.v1.WorkflowService"
IDLE_TIMEOUT = 1800
# HAProxy may bind :443 slightly after Juju reports it active; retry the gRPC
# health check for this long before giving up.
GRPC_READY_TIMEOUT = 300


def _controller_by_cloud(*clouds: str) -> str:
    """Return the name of the bootstrapped controller backed by one of ``clouds``."""
    output = jubilant.Juju().cli("controllers", "--format", "json", include_model=False)
    controllers = json.loads(output)["controllers"]
    for name, info in controllers.items():
        if info.get("cloud") in clouds:
            return name
    raise RuntimeError(f"no controller found for clouds {clouds}; check concierge bootstrapped it")


@pytest.fixture(scope="module")
def charm_path(pytestconfig) -> Path:
    """Path to the packed charm (built with charmcraft if not supplied).

    Returned as a ``Path`` (not ``str``): jubilant only auto-prefixes relative
    local-charm paths with ``./`` (to disambiguate them from Charmhub names) when
    given a ``pathlib.Path`` - a bare filename string is passed to the Juju CLI
    unprefixed and rejected as ambiguous.
    """
    supplied = pytestconfig.getoption("--charm-file", default=None)
    if supplied:
        return Path(supplied)
    subprocess.run(["charmcraft", "pack"], check=True)  # noqa: S603, S607
    return sorted(Path(".").glob(f"{APP_NAME}_*.charm"))[0]


def _collect_debug_log(juju: jubilant.Juju) -> None:
    """Print the model's status and Juju debug log to stderr.

    Called on any failure (setup or test) so CI always has something to go on.
    Both the final status and the replayed debug log are dumped: a hook
    traceback (e.g. ``hook failed: "admin-relation-changed"``) shows up in the
    debug log, which the bare timeout status dump never captures.
    """
    time.sleep(0.5)  # Wait for Juju to process logs.
    banner = f"{'=' * 30} debug output for model {juju.model} {'=' * 30}"
    print(banner, file=sys.stderr)
    try:
        print(juju.status(), file=sys.stderr)
        # 3000 lines and --level covers the deploy window without burying the
        # traceback; replay is on by default so earlier hook errors are included.
        print(juju.debug_log(limit=3000), end="", file=sys.stderr)
    except Exception as err:  # noqa: BLE001 - best-effort diagnostics, never mask the real failure
        print(f"failed to collect debug output for {juju.model}: {err}", file=sys.stderr)
    print("=" * len(banner), file=sys.stderr)


@pytest.fixture(scope="module")
def topology(request: pytest.FixtureRequest, charm_path):
    """Deploy the full cross-model topology in temporary k8s and LXD models."""
    k8s_ctrl = _controller_by_cloud("k8s", "microk8s")
    lxd_ctrl = _controller_by_cloud("localhost", "lxd")

    with jubilant.temp_model(controller=k8s_ctrl) as k8s_juju, jubilant.temp_model(controller=lxd_ctrl) as lxd_juju:
        k8s_juju.wait_timeout = IDLE_TIMEOUT
        lxd_juju.wait_timeout = IDLE_TIMEOUT

        try:
            resources = {"temporal-server-image": METADATA["resources"]["temporal-server-image"]["upstream-source"]}

            # --- Kubernetes model ---
            k8s_juju.deploy(charm_path, APP_NAME, resources=resources, config={"num-history-shards": 2})
            k8s_juju.deploy(TEMPORAL_ADMIN, channel=TEMPORAL_CHANNEL)
            k8s_juju.deploy(POSTGRESQL_K8S, channel=POSTGRESQL_CHANNEL, trust=True)
            k8s_juju.deploy(SELF_SIGNED, channel=SELF_SIGNED_CERTIFICATES_CHANNEL)
            k8s_juju.deploy(INGRESS_CONFIGURATOR, channel=INGRESS_CONFIGURATOR_CHANNEL, trust=True)

            k8s_juju.integrate(f"{APP_NAME}:db", f"{POSTGRESQL_K8S}:database")
            k8s_juju.integrate(f"{APP_NAME}:visibility", f"{POSTGRESQL_K8S}:database")
            k8s_juju.integrate(f"{APP_NAME}:admin", f"{TEMPORAL_ADMIN}:admin")
            # Frontend serves gRPC over TLS.
            k8s_juju.integrate(f"{APP_NAME}:frontend-certificates", f"{SELF_SIGNED}:certificates")
            # Workload -> ingress-configurator (backend spoken over TLS).
            k8s_juju.integrate(f"{APP_NAME}:ingress", f"{INGRESS_CONFIGURATOR}:ingress")
            k8s_juju.config(INGRESS_CONFIGURATOR, {"hostname": HOSTNAME, "backend-protocol": "https"})

            # --- Machine model ---
            lxd_juju.deploy(HAPROXY, channel=HAPROXY_CHANNEL)
            lxd_juju.deploy(SELF_SIGNED, channel=SELF_SIGNED_CERTIFICATES_CHANNEL)
            lxd_juju.integrate(f"{HAPROXY}:certificates", SELF_SIGNED)
            lxd_juju.config(HAPROXY, {"external-hostname": HOSTNAME})

            # --- Cross-model: route + backend-CA trust ---
            # `.model` may carry a controller prefix (set by `add_model(controller=...)`); strip it
            # since `consume()` takes the bare model name and the controller separately.
            lxd_model = lxd_juju.model.rpartition(":")[2]
            k8s_model = k8s_juju.model.rpartition(":")[2]

            lxd_juju.offer(HAPROXY, endpoint="haproxy-route")
            k8s_juju.consume(f"{lxd_model}.{HAPROXY}", "haproxy-cmr", controller=lxd_ctrl)
            k8s_juju.integrate(f"{INGRESS_CONFIGURATOR}:haproxy-route", "haproxy-cmr")

            k8s_juju.offer(SELF_SIGNED, endpoint="send-ca-cert")
            lxd_juju.consume(f"{k8s_model}.{SELF_SIGNED}", "frontend-ca", controller=k8s_ctrl)
            lxd_juju.integrate(f"{HAPROXY}:receive-ca-certs", "frontend-ca")

            # --- Wait for both models to settle ---
            # `error=jubilant.any_error` aborts in seconds on a hook failure
            # (e.g. `hook failed: "admin-relation-changed"`) instead of sitting
            # through the full IDLE_TIMEOUT and destroying the models before the
            # cause is ever captured.
            #
            # Wait for ingress-configurator (the haproxy-route provider) as well as
            # agents-idle: HAProxy only requests its cert and binds :443 once the
            # cross-model route has fully propagated, so waiting on the workload
            # alone races the HAProxy config reload.
            k8s_juju.wait(
                lambda status: jubilant.all_active(status, APP_NAME, INGRESS_CONFIGURATOR)
                and jubilant.all_agents_idle(status, APP_NAME, INGRESS_CONFIGURATOR),
                error=jubilant.any_error,
                timeout=IDLE_TIMEOUT,
            )
            lxd_juju.wait(
                lambda status: jubilant.all_active(status, HAPROXY) and jubilant.all_agents_idle(status, HAPROXY),
                error=jubilant.any_error,
                timeout=IDLE_TIMEOUT,
            )
        except Exception:
            # Setup failures happen before `yield`, so the post-yield block below
            # never runs; capture logs here too or CI is left with only jubilant's
            # status dump and no juju debug-log.
            _collect_debug_log(k8s_juju)
            _collect_debug_log(lxd_juju)
            raise

        yield {"k8s_juju": k8s_juju, "lxd_juju": lxd_juju}

        if request.session.testsfailed:
            _collect_debug_log(k8s_juju)
            _collect_debug_log(lxd_juju)


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
    assert der_cert is not None, "peer did not present a certificate"
    return ssl.DER_cert_to_PEM_cert(der_cert).encode()


def _check_grpc_health(haproxy_ip: str) -> "health_pb2.HealthCheckResponse.ServingStatus":
    """Run one gRPC health check against HAProxy's TLS frontend.

    Verified TLS: trust HAProxy's presented cert, and set SNI/authority to the
    routing hostname so HAProxy's host-based route matches.
    """
    root_certificate = _server_certificate(haproxy_ip, 443, HOSTNAME)
    credentials = grpc.ssl_channel_credentials(root_certificates=root_certificate)
    options = (
        ("grpc.ssl_target_name_override", HOSTNAME),
        ("grpc.default_authority", HOSTNAME),
    )
    with grpc.secure_channel(f"{haproxy_ip}:443", credentials, options=options) as channel:
        stub = health_pb2_grpc.HealthStub(channel)
        request = health_pb2.HealthCheckRequest(service=FRONTEND_GRPC_SERVICE)
        return stub.Check(request, timeout=30).status


@pytest.mark.abort_on_fail
def test_grpc_over_tls(topology):
    """The Temporal frontend is reachable via gRPC over TLS through HAProxy."""
    lxd_status = topology["lxd_juju"].status()
    haproxy_ip = lxd_status.apps[HAPROXY].units[f"{HAPROXY}/0"].public_address

    # HAProxy binds :443 and reloads its config a moment after Juju reports it
    # active (cert write + reload), so an immediate connect can hit "connection
    # refused". Retry until the frontend serves or the deadline passes.
    deadline = time.monotonic() + GRPC_READY_TIMEOUT
    while True:
        try:
            status = _check_grpc_health(haproxy_ip)
            assert status == health_pb2.HealthCheckResponse.SERVING
            return
        except (OSError, grpc.RpcError, AssertionError):
            if time.monotonic() >= deadline:
                raise
            time.sleep(5)
