#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.
#
# Learn more at: https://juju.is/docs/sdk

"""Charm definition and helpers."""

import functools
import logging
import os
import re
import socket
from typing import Optional

from charms.data_platform_libs.v0.data_interfaces import DatabaseRequires
from charms.data_platform_libs.v0.s3 import S3Requirer
from charms.grafana_k8s.v0.grafana_dashboard import GrafanaDashboardProvider
from charms.loki_k8s.v1.loki_push_api import LogForwarder, LogProxyConsumer
from charms.nginx_ingress_integrator.v0.nginx_route import require_nginx_route
from charms.openfga_k8s.v1.openfga import OpenFGARequires
from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointProvider
from charms.temporal_k8s.v0.temporal_host_info import TemporalHostInfoProvider
from charms.tls_certificates_interface.v4.tls_certificates import (
    Certificate,
    CertificateRequestAttributes,
    Mode,
    PrivateKey,
    ProviderCertificate,
    TLSCertificatesRequiresV4,
)
from jinja2 import Environment, FileSystemLoader
from ops import CollectStatusEvent, EventBase, main, pebble
from ops.charm import CharmBase, RelationBrokenEvent
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, WaitingStatus
from ops.pebble import CheckStatus

from literals import (
    DB_NAME,
    LOG_FORMAT,
    LOG_OUTPUT_FILE,
    PROMETHEUS_PORT,
    REQUIRED_OPENFGA_KEYS,
    REQUIRED_S3_PARAMETERS,
    SERVICE_PORTS,
    VALID_LOG_LEVELS,
    VISIBILITY_DB_NAME,
    WORKLOAD_VERSION,
    ValidServiceTypes,
)
from log import log_event_handler

# import relations
from relations.admin import Admin
from relations.openfga import OpenFGA
from relations.postgresql import Postgresql
from relations.s3_archival import S3Integrator
from relations.ui import UI
from state import State

CERTIFICATE_NAME = "temporal-frontend.pem"
CERTS_DIR_PATH = "/etc/temporal"
FRONTEND_CERTIFICATES_RELATION_NAME = "frontend-certificates"
PRIVATE_KEY_NAME = "temporal-frontend.key"
FRONTEND_TLS_CONFIGURATION = {
    "TEMPORAL_TLS_REQUIRE_CLIENT_AUTH": "false",
    "TEMPORAL_TLS_FRONTEND_CERT": f"{CERTS_DIR_PATH}/{CERTIFICATE_NAME}",
    "TEMPORAL_TLS_FRONTEND_KEY": f"{CERTS_DIR_PATH}/{PRIVATE_KEY_NAME}",
}
logger = logging.getLogger(__name__)


def render(template_name, context):
    """Render the template with the given name using the given context dict.

    Args:
        template_name: File name to read the template from.
        context: Dict used for rendering.

    Returns:
        A dict containing the rendered template.
    """
    charm_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
    loader = FileSystemLoader(os.path.join(charm_dir, "templates"))
    return Environment(loader=loader, autoescape=True).get_template(template_name).render(**context)


def is_valid_time_duration(duration_str):
    """Validate time duration.

    Args:
        duration_str: time duration string.

    Returns:
        True if the time duration is valid, False otherwise.
    """
    allowed_pattern = r"^[1-9]\d*[smh]$"
    return bool(re.match(allowed_pattern, duration_str))


class TemporalK8SCharm(CharmBase):
    """Temporal server charm.

    Attrs:
        _state: used to store data that is persisted across invocations.
        external_hostname: DNS listing used for external connections.
    """

    @property
    def external_hostname(self):
        """Return the DNS listing used for external connections."""
        return self.config["external-hostname"] or self.app.name

    def __init__(self, *args):
        """Construct.

        Args:
            args: Ignore.
        """
        super().__init__(*args)
        self._state = State(self.app, lambda: self.model.get_relation("peer"))
        self.name = "temporal"
        self.container = self.unit.get_container("temporal")
        self._dns_entries = [
            dns.strip() for dns in self.config.get("frontend-cert-sans-dns", "").split(",") if dns.strip()
        ]

        # Initialize libraries (these remain as utility objects, but no longer register observers).
        self.db = DatabaseRequires(self, relation_name="db", database_name=DB_NAME, extra_user_roles="admin")
        self.visibility = DatabaseRequires(
            self,
            relation_name="visibility",
            database_name=VISIBILITY_DB_NAME,
            extra_user_roles="admin",
        )
        self.postgresql = Postgresql(self)
        self.admin = Admin(self)
        self.ui = UI(self)
        self.openfga = OpenFGARequires(self, self.name)
        self.openfga_relation = OpenFGA(self)
        self.s3_client = S3Requirer(self, "s3-parameters")
        self.s3_relation = S3Integrator(self)

        # Ingress
        self._require_nginx_route()

        # Observability libraries (these manage their own observers internally).
        self._prometheus_scraping = MetricsEndpointProvider(
            self,
            relation_name="metrics-endpoint",
            jobs=[{"static_configs": [{"targets": [f"*:{PROMETHEUS_PORT}"]}]}],
            refresh_event=self.on.config_changed,
        )
        self._log_forwarder = LogForwarder(self, relation_name="logging")
        self._log_proxy = LogProxyConsumer(
            self,
            logs_scheme={"temporal": {"log-files": [LOG_OUTPUT_FILE]}},
            relation_name="log-proxy",
        )
        self._grafana_dashboards = GrafanaDashboardProvider(self, relation_name="grafana-dashboard")

        # Frontend TLS certificates (library manages its own refresh_events observers).
        self.certificates = TLSCertificatesRequiresV4(
            charm=self,
            relationship_name=FRONTEND_CERTIFICATES_RELATION_NAME,
            certificate_requests=[self._get_certificate_request_attributes()],
            mode=Mode.UNIT,
            refresh_events=[self.on.upgrade_charm, self.on.config_changed],
        )

        # Host Info
        self._host_info = TemporalHostInfoProvider(self, SERVICE_PORTS["frontend"]["grpc"])

        # === Consolidated event observation ===
        # All reconcilable events route to a single _reconcile entry point.
        reconcile_events = [
            # Charm lifecycle
            self.on.install,
            self.on.start,
            self.on.config_changed,
            self.on.upgrade_charm,
            self.on.update_status,
            self.on.temporal_pebble_ready,
            # Peer
            self.on.peer_relation_changed,
            # PostgreSQL (library custom events)
            self.db.on.database_created,
            self.db.on.endpoints_changed,
            self.visibility.on.database_created,
            self.visibility.on.endpoints_changed,
            # PostgreSQL relation broken
            self.on.db_relation_broken,
            self.on.visibility_relation_broken,
            # Admin
            self.on.admin_relation_joined,
            self.on.admin_relation_changed,
            # UI
            self.on.ui_relation_joined,
            self.on.ui_relation_changed,
            # OpenFGA (library custom event)
            self.openfga.on.openfga_store_created,
            self.on.openfga_relation_broken,
            # S3 (library custom events)
            self.s3_client.on.credentials_changed,
            self.s3_client.on.credentials_gone,
            # Frontend TLS certificates
            self.certificates.on.certificate_available,
            self.on[FRONTEND_CERTIFICATES_RELATION_NAME].relation_joined,
            self.on[FRONTEND_CERTIFICATES_RELATION_NAME].relation_broken,
        ]
        for event in reconcile_events:
            self.framework.observe(event, self._reconcile)

        # Dedicated handlers: actions (synchronous, need args/results)
        self.framework.observe(self.on.restart_action, self._on_restart_action)
        self.framework.observe(self.on.create_authorization_model_action, self.openfga_relation._on_create_authorization_model_action)
        self.framework.observe(self.on.add_auth_rule_action, self.openfga_relation._on_add_auth_rule_action)
        self.framework.observe(self.on.remove_auth_rule_action, self.openfga_relation._on_remove_auth_rule_action)
        self.framework.observe(self.on.list_auth_rule_action, self.openfga_relation._on_list_auth_rule_action)
        self.framework.observe(self.on.check_auth_rule_action, self.openfga_relation._on_check_auth_rule_action)
        self.framework.observe(self.on.list_system_admins_action, self.openfga_relation._on_list_system_admins_action)

        # Dedicated handler: status reporting
        self.framework.observe(self.on.collect_unit_status, self._on_collect_unit_status)

    # ── Reconciler ──────────────────────────────────────────────────────────

    def _reconcile(self, event: EventBase) -> None:
        """Central reconciliation loop: read → compute → write.

        All reconcilable events are routed here. The event payload is ignored;
        we read the full state of the world on every invocation.

        Args:
            event: The event that triggered reconciliation (ignored).
        """
        # ── Early-exit guards ──────────────────────────────────────────────
        container = self.unit.get_container(self.name)
        if not container.can_connect():
            logger.info("Container not yet connectable, deferring reconcile")
            return

        if not self._state.is_ready():
            logger.info("Peer relation not ready, deferring reconcile")
            return

        # ── Phase 1: Read inputs ───────────────────────────────────────────

        # Update database connection state from relation data (leader only).
        if self.unit.is_leader():
            self.postgresql.update_db_relation_data_in_state()

            # Handle db/visibility relation-broken: clear the broken side.
            if isinstance(event, RelationBrokenEvent) and event.relation.name in ("db", "visibility"):
                self.postgresql._update_db_connections(event.relation.name, None)

            # Handle openfga relation events.
            self._read_openfga_state(event)

            # Handle S3 relation events.
            self._read_s3_state(event)

            # Read schema_ready from admin relation data.
            self._read_admin_schema_state()

            # Handle openfga relation-broken.
            if isinstance(event, RelationBrokenEvent) and event.relation.name == "openfga":
                self._state.openfga = None

            # Handle s3 relation-broken (credentials_gone sets state to None).

        # Validate configuration and relation readiness.
        try:
            self._validate()
        except ValueError as err:
            logger.info(f"Validation failed: {err}")
            return

        # DNS validation for frontend certificates.
        invalid_dns = [dns for dns in self._dns_entries if not self._valid_dns(dns)]
        if invalid_dns:
            logger.info(f"Invalid frontend-cert-sans-dns: {invalid_dns}")
            return

        # ── Phase 2: Compute new state ─────────────────────────────────────

        if self.unit.is_leader():
            self._open_service_ports()

        context = self._build_environment_context()

        # Compute frontend TLS context (replaces _handle_frontend_tls + _extra_context).
        tls_context, tls_certs_updated = self._compute_frontend_tls_context(event)
        context.update(tls_context)

        # Handle certificate removal on relation-broken.
        if isinstance(event, RelationBrokenEvent) and event.relation.name == FRONTEND_CERTIFICATES_RELATION_NAME:
            self._delete_certificate()
            self._delete_private_key()

        # Render config templates.
        config = render("config.jinja", context)
        dynamic_context = {
            "GLOBAL_RPS_LIMIT": self.config["global-rps-limit"],
            "NAMESPACE_RPS_LIMIT": self.config["namespace-rps-limit"],
            "LONG_POLL_INTERVAL": self.config["long-poll-interval"],
        }
        dynamic_config = render("dynamic_config.jinja", dynamic_context)

        # Build the desired Pebble layer.
        services = self.config["services"].split(",")
        services_args = " ".join(f"--service={service}" for service in services)
        if ValidServiceTypes.FRONTEND.value in services:
            services_args += " --service=internal-frontend"

        new_layer = {
            "summary": "temporal server layer",
            "services": {
                "temporal-server": {
                    "summary": "temporal server",
                    "command": "temporal-server --env charm start " + services_args,
                    "startup": "enabled",
                    "override": "replace",
                    "environment": context,
                    "on-check-failure": {"temporal-server-running": "ignore"},
                    "user": "ubuntu",
                    "working-dir": "/etc/temporal",
                }
            },
            "checks": {
                "temporal-server-running": {
                    "override": "replace",
                    "level": "alive",
                    "period": "300s",
                    "exec": {"command": "temporal operator cluster health --address=temporal-k8s:7236"},
                }
            },
        }

        # ── Phase 3: Write outputs (only if changed) ───────────────────────

        logger.info("configuring temporal")

        # Ensure log directory exists.
        log_dir = os.path.dirname(LOG_OUTPUT_FILE)
        container.make_dir(log_dir, make_parents=True, user="ubuntu", group="ubuntu")

        # Push log rotation config.
        logrotate_config = f"""{LOG_OUTPUT_FILE} {{
    daily
    rotate 7
    size 100M
    missingok
    notifempty
    nomail
    compress
    delaycompress
    copytruncate
    create 0640 ubuntu ubuntu
}}
"""
        container.push("/etc/logrotate.d/temporal-server", logrotate_config, make_dirs=True)

        # Push rendered config files.
        container.push("/etc/temporal/config/charm.yaml", config, make_dirs=True)
        container.push("/etc/temporal/config/dynamicconfig/docker.yaml", dynamic_config, make_dirs=True)

        # Pebble layer diffing: only replan if the layer has materially changed.
        current_plan = container.get_plan().to_dict()
        if self._pebble_layer_changed(current_plan, new_layer):
            logger.info("Pebble layer changed, replanning")
            container.add_layer(self.name, new_layer, combine=True)
            container.replan()
        else:
            logger.info("Pebble layer unchanged, skipping replan")

        # Run log rotation.
        self._run_log_rotation(container)

        # Write provider relation data.
        if self.unit.is_leader():
            self.admin._provide_db_info()
            self.ui._provide_server_status()

        self.unit.set_workload_version(WORKLOAD_VERSION)

    # ── Reconciler helpers ────────────────────────────────────────────────

    def _pebble_layer_changed(self, current_plan: dict, new_layer: dict) -> bool:
        """Compare current Pebble plan against the desired layer.

        Args:
            current_plan: The current plan dict from container.get_plan().
            new_layer: The desired layer dict.

        Returns:
            True if the layer differs and a replan is needed.
        """
        # Compare services and checks sections.
        current_services = current_plan.get("services", {})
        current_checks = current_plan.get("checks", {})
        new_services = new_layer.get("services", {})
        new_checks = new_layer.get("checks", {})
        return current_services != new_services or current_checks != new_checks

    def _build_environment_context(self) -> dict:
        """Build the environment context dict for the Temporal server.

        Returns:
            Environment context dict.
        """
        context = {"LOG_LEVEL": self.config["log-level"]}
        context.update(
            {
                "LOG_OUTPUT_FILE": LOG_OUTPUT_FILE,
                "LOG_FORMAT": LOG_FORMAT,
            }
        )
        db_conn = self._state.database_connections["db"]
        visibility_conn = self._state.database_connections["visibility"]
        context.update(
            {
                "DB_NAME": db_conn["dbname"],
                "DB_HOST": db_conn["host"],
                "DB_PORT": db_conn["port"],
                "DB_USER": db_conn["user"],
                "DB_PSWD": db_conn["password"],
                "VISIBILITY_NAME": visibility_conn["dbname"],
                "VISIBILITY_HOST": visibility_conn["host"],
                "VISIBILITY_PORT": visibility_conn["port"],
                "VISIBILITY_USER": visibility_conn["user"],
                "VISIBILITY_PSWD": visibility_conn["password"],
                "TEMPORAL_BROADCAST_ADDRESS": str(self.model.get_binding("peer").network.bind_address),
                "NUM_HISTORY_SHARDS": self._state.num_history_shards,
                "SQL_MAX_CONNS": self.config["persistence-max-conns"],
                "SQL_MAX_IDLE_CONNS": self.config["persistence-max-idle-conns"],
                "SQL_MAX_CONN_TIME": self.config["persistence-max-conn-time"],
                "SQL_VIS_MAX_CONNS": self.config["visibility-max-conns"],
                "SQL_VIS_MAX_IDLE_CONNS": self.config["visibility-max-idle-conns"],
                "SQL_VIS_MAX_CONN_TIME": self.config["visibility-max-conn-time"],
                "SQL_TLS_ENABLED": db_conn.get("tls", False),
            }
        )

        if self.config["auth-enabled"]:
            openfga = self._state.openfga
            context.update(
                {
                    "AUTH_ENABLED": True,
                    "OFGA_STORE_ID": openfga.get("store_id"),
                    "OFGA_AUTH_MODEL_ID": openfga.get("auth_model_id"),
                    "OFGA_API_HOST": openfga.get("address"),
                    "OFGA_API_SCHEME": openfga.get("scheme"),
                    "OFGA_SECRETS_BEARER_TOKEN": openfga.get("token"),
                    "OFGA_API_PORT": openfga.get("port"),
                    "AUTH_ADMIN_GROUPS": self.config["auth-admin-groups"],
                    "AUTH_OPEN_ACCESS_NAMESPACES": self.config["auth-open-access-namespaces"],
                    "AUTH_GOOGLE_CLIENT_ID": self.config["auth-google-client-id"],
                }
            )

        http_proxy = os.environ.get("JUJU_CHARM_HTTP_PROXY")
        https_proxy = os.environ.get("JUJU_CHARM_HTTPS_PROXY")
        no_proxy = os.environ.get("JUJU_CHARM_NO_PROXY")

        if http_proxy or https_proxy:
            context.update(
                {
                    "HTTP_PROXY": http_proxy,
                    "HTTPS_PROXY": https_proxy,
                    "NO_PROXY": no_proxy,
                }
            )

        if self._state.s3:
            context.update(
                {
                    "ARCHIVAL_ENABLED": True,
                    "ARCHIVAL_BUCKET_REGION": self._state.s3.get("region"),
                    "ARCHIVAL_ENDPOINT": self._state.s3.get("endpoint"),
                    "ARCHIVAL_URI_STYLE": self._state.s3.get("uri_style"),
                    "AWS_ACCESS_KEY_ID": self._state.s3.get("aws_access_key_id"),
                    "AWS_SECRET_ACCESS_KEY": self._state.s3.get("aws_secret_access_key"),
                }
            )

        return context

    def _compute_frontend_tls_context(self, event: EventBase) -> tuple[dict, bool]:
        """Compute frontend TLS environment variables and update certificates if needed.

        Replaces the old _handle_frontend_tls + _extra_context side-effect pattern.

        Args:
            event: The event that triggered reconciliation.

        Returns:
            Tuple of (tls_context_dict, certificates_were_updated).
        """
        # Not a frontend service but has the relation — validation will catch this
        # via _on_collect_unit_status, but we skip TLS context here.
        if "frontend" not in self.config["services"]:
            return {}, False

        if not self._relation_created(FRONTEND_CERTIFICATES_RELATION_NAME):
            return {}, False

        provider_certificate, private_key = self.certificates.get_assigned_certificate(
            certificate_request=self._get_certificate_request_attributes()
        )

        if not provider_certificate or not private_key:
            logger.info("The certificate is not available yet.")
            return {}, False

        # Update certificates in the container if needed.
        certs_updated = False
        if self._update_certificates_required(provider_certificate, private_key):
            self._store_certificate(certificate=provider_certificate.certificate)
            self._store_private_key(private_key=private_key)
            certs_updated = True

        return dict(FRONTEND_TLS_CONFIGURATION), certs_updated

    def _read_openfga_state(self, event: EventBase) -> None:
        """Read OpenFGA store info from the relation into peer state.

        Args:
            event: The triggering event.
        """
        from charms.openfga_k8s.v1.openfga import OpenFGAStoreCreateEvent

        if not isinstance(event, OpenFGAStoreCreateEvent):
            return

        if not event.store_id:
            logger.info("openfga relation revoked, no store id")
            return

        info = self.openfga.get_store_info()
        if not info:
            logger.info("openfga relation revoked, no store info found")
            return

        from urllib.parse import urlsplit

        url_components = urlsplit(info.http_api_url)
        self._state.openfga = {
            "store_id": info.store_id,
            "token": info.token,
            "address": url_components.hostname,
            "port": url_components.port,
            "scheme": url_components.scheme,
            "auth_model_id": None,
        }

    def _read_s3_state(self, event: EventBase) -> None:
        """Read S3 credentials from the relation into peer state.

        Args:
            event: The triggering event.
        """
        from charms.data_platform_libs.v0.s3 import CredentialsChangedEvent, CredentialsGoneEvent

        if isinstance(event, CredentialsGoneEvent):
            self._state.s3 = None
            return

        if not isinstance(event, CredentialsChangedEvent):
            return

        s3_parameters, missing_parameters = self.s3_relation._retrieve_s3_parameters()
        if missing_parameters:
            return

        from relations.s3_archival import _construct_endpoint, _create_bucket_if_not_exists
        from botocore.exceptions import ClientError

        endpoint = _construct_endpoint(s3_parameters)
        bucket_created = True
        try:
            _create_bucket_if_not_exists(s3_parameters, endpoint)
        except (ClientError, ValueError):
            bucket_created = False

        self._state.s3 = {
            "bucket": s3_parameters.get("bucket"),
            "endpoint": endpoint,
            "region": s3_parameters.get("region"),
            "aws_access_key_id": s3_parameters.get("access-key"),
            "aws_secret_access_key": s3_parameters.get("secret-key"),
            "uri_style": s3_parameters.get("s3-uri-style"),
            "bucket_created": bucket_created,
        }

    def _read_admin_schema_state(self) -> None:
        """Read schema_ready directly from admin relation data into peer state."""
        admin_relations = self.model.relations.get("admin")
        if not admin_relations:
            return

        for relation in admin_relations:
            if relation.app and relation.data.get(relation.app):
                schema_ready = relation.data[relation.app].get("schema_status") == "ready"
                self._state.schema_ready = schema_ready
                return

    # ── Status reporting ──────────────────────────────────────────────────

    def _on_collect_unit_status(self, event: CollectStatusEvent) -> None:
        """Report unit status based on current state.

        All status decisions are centralized here.

        Args:
            event: The collect-unit-status event.
        """
        container = self.unit.get_container(self.name)
        if not container.can_connect():
            event.add_status(WaitingStatus("Waiting for Pebble"))
            return

        if not self._state.is_ready():
            event.add_status(WaitingStatus("Waiting for peer relation"))
            return

        # DNS validation.
        invalid_dns = [dns for dns in self._dns_entries if not self._valid_dns(dns)]
        if invalid_dns:
            event.add_status(BlockedStatus("Invalid frontend-cert-sans-dns, please correct the value(s)."))
            return

        # Frontend TLS vs non-frontend conflict.
        if "frontend" not in self.config["services"] and self.model.get_relation(FRONTEND_CERTIFICATES_RELATION_NAME):
            event.add_status(
                BlockedStatus(
                    f"Not a frontend service, please remove {FRONTEND_CERTIFICATES_RELATION_NAME} integration."
                )
            )
            return

        # Waiting for frontend certificates.
        if self._relation_created(FRONTEND_CERTIFICATES_RELATION_NAME) and "frontend" in self.config["services"]:
            provider_certificate, private_key = self.certificates.get_assigned_certificate(
                certificate_request=self._get_certificate_request_attributes()
            )
            if not provider_certificate or not private_key:
                event.add_status(WaitingStatus("Waiting for certificates to be available"))
                return

        # Validate config and relations.
        try:
            self._validate()
        except ValueError as err:
            event.add_status(BlockedStatus(str(err)))
            return

        # Check Pebble health.
        try:
            check = container.get_check("temporal-server-running")
            if check.status != CheckStatus.UP:
                event.add_status(MaintenanceStatus("Status check: DOWN"))
                return
        except (KeyError, pebble.ConnectionError):
            # Check not yet configured.
            event.add_status(WaitingStatus("Waiting for Pebble plan"))
            return

        message = "auth enabled" if self.config["auth-enabled"] else ""
        event.add_status(ActiveStatus(message))

    def _require_nginx_route(self):
        """Require nginx-route relation based on current configuration."""
        require_nginx_route(
            charm=self,
            service_hostname=self.external_hostname,
            service_name=self.app.name,
            service_port=SERVICE_PORTS["frontend"]["grpc"],
            tls_secret_name=self.config["tls-secret-name"],
            backend_protocol="GRPC",
        )

    def database_connections(self):
        """Return connection info for the related databases.

        The connection info is returned as a dict like the following:

            {
                "db": {
                    "dbname": "...",
                    "host": "...",
                    "port": "...",
                    "user": "...",
                    "password": "...",
                },  # or None.

                "visibility": {
                    "dbname": "...",
                    "host": "...",
                    "port": "...",
                    "user": "...",
                    "password": "...",
                },  # or None.
            }

        Raises:
            ValueError: one of the databases is not connected yet

        Returns:
            DB connection info dict.
        """
        # Copy key/value pairs in a new dict as self._state.database_connections
        # and its values (of type ops.framework.StoredDict) are not serializable.
        database_connections = {}

        if self._state.database_connections is None or self._state.database_connections == {
            "db": None,
            "visibility": None,
        }:
            raise ValueError("database relation not ready")

        for rel_name, db_conn in self._state.database_connections.items():
            if db_conn is None:
                raise ValueError(f"{rel_name}:pgsql relation: no database connection available")
            database_connections[rel_name] = dict(db_conn)
        return database_connections



    @log_event_handler(logger)
    def _on_restart_action(self, event):
        """Restart the temporal server, even if there are no changes.

        Args:
            event: The event triggered when the relation changed.
        """
        container = self.unit.get_container(self.name)

        logger.info("restarting temporal")
        container.restart(self.name)

    def _run_log_rotation(self, container):
        """Run log rotation for temporal server logs.

        logrotate only rotates when the configured
        conditions are met (file size or time threshold).

        Args:
            container: application container
        """
        try:
            container.exec(["logrotate", "/etc/logrotate.d/temporal-server"]).wait()
        except (pebble.ExecError, pebble.APIError) as e:
            logger.warning(f"Log rotation failed: {e}")

    def _check_missing_params(self, params, required_params):
        """Validate that all required properties were extracted.

        Args:
            params: dictionary of parameters extracted from relation.
            required_params: list of required parameters.

        Returns:
            list: List of OpenFGA parameters that are not set in state.
        """
        missing_params = []
        for key in required_params:
            if params.get(key) is None:
                missing_params.append(key)
        return missing_params

    # flake8: noqa: C901
    def _validate(self):
        """Validate that configuration and relations are valid and ready.

        Raises:
            ValueError: in case of invalid configuration.
        """
        log_level = self.model.config["log-level"].lower()
        if log_level not in VALID_LOG_LEVELS:
            raise ValueError(f"config: invalid log level {log_level!r}")
        if not self._state.is_ready():
            raise ValueError("peer relation not ready")

        # Validate config.
        for service in self.config["services"].split(","):
            if not any(service == item.value for item in ValidServiceTypes):
                raise ValueError(f"error in services config: invalid service {service!r}")

        num_history_shards = self._state.num_history_shards
        if num_history_shards is None:
            if self.config.get("num-history-shards", "") == "" or self.config.get("num-history-shards") <= 0:
                raise ValueError(
                    "value of 'num-history-shards' config must be set to a positive power of 2 (e.g. 1, 2, 4)"
                )

            if self.unit.is_leader():
                self._state.num_history_shards = self.config.get("num-history-shards")

        elif num_history_shards != self.config["num-history-shards"]:
            message = f"value of 'num-history-shards' config cannot be changed after deployment. Value should be {num_history_shards}"
            logger.error(message)
            raise ValueError(message)

        if self.config["global-rps-limit"] < 0:
            raise ValueError("`global-rps-limit` must be grater than 0")

        db_types = ["persistence", "visibility"]
        for db_type in db_types:
            if self.config[f"{db_type}-max-conns"] < 1:
                raise ValueError(f"value of '{db_type}-max-conns' must be >= 1")
            if self.config[f"{db_type}-max-idle-conns"] < 1:
                raise ValueError(f"value of '{db_type}-max-idle-conns' must be >= 1")
            if not is_valid_time_duration(self.config[f"{db_type}-max-conn-time"]):
                raise ValueError(f"value of '{db_type}-max-conn-time' must be a valid time duration e.g. 1h")

        # Validate admin relation.
        self.database_connections()
        if "frontend" in self.config["services"] and not self._state.schema_ready:
            raise ValueError("admin:temporal relation: schema is not ready")

        # Validate OpenFGA relation.
        if self.config["auth-enabled"]:
            if not self._state.openfga:
                raise ValueError("openfga:temporal relation not ready")
            missing_params = self._check_missing_params(self._state.openfga, REQUIRED_OPENFGA_KEYS)
            if len(missing_params) > 0:
                raise ValueError(f"openfga:missing parameters {missing_params!r}")
            if not self._state.openfga["auth_model_id"]:
                raise ValueError("missing openfga authorization model")

        # Validate S3 relation.
        if self._state.s3:
            missing_params = self._check_missing_params(self._state.s3, REQUIRED_S3_PARAMETERS)
            if len(missing_params) > 0:
                raise ValueError(f"s3:missing parameters {missing_params!r}")

            if not self._state.s3.get("bucket_created"):
                raise ValueError("s3:archival failed to create s3 bucket.")

    def _open_service_ports(self):
        """Open the respective ports based on Temporal service."""
        services = self.config["services"]

        open_port = functools.partial(self.model.unit.open_port, protocol="tcp")
        close_port = functools.partial(self.model.unit.close_port, protocol="tcp")

        for service, ports in SERVICE_PORTS.items():
            if service in services:
                open_port(port=ports["grpc"])
                open_port(port=ports["http"])
            else:
                close_port(port=ports["grpc"])
                close_port(port=ports["http"])

        if "frontend" in services:
            open_port(port=SERVICE_PORTS["internal-frontend"]["grpc"])
            open_port(port=SERVICE_PORTS["internal-frontend"]["http"])
        else:
            close_port(port=SERVICE_PORTS["internal-frontend"]["grpc"])
            close_port(port=SERVICE_PORTS["internal-frontend"]["http"])



    # Helpers for frontend TLS
    def _relation_created(self, relation_name: str) -> bool:
        return bool(self.model.relations.get(relation_name))

    def _valid_dns(self, dns: str) -> bool:
        """Return True if the DNS is RFC compliant, False otherwise.

        Args:
          dns: a SANS DNS to validate.
        """
        # Immediately return False if the SANS DNS does not exist or is larger than 253 chars
        if not dns or len(dns) > 253:
            return False

        # Check the labels (each part of the domain between the dots)
        for label in dns.rstrip(".").split("."):
            if len(label) == 0 or len(label) > 63:
                return False
            if not re.fullmatch(r"[A-Za-z0-9-]{1,63}", label):
                return False
            if label.startswith("-") or label.endswith("-"):
                return False

        # If everything is alright, return True
        return True

    def _get_certificate_request_attributes(self) -> CertificateRequestAttributes:
        """Return the attributes of the certificate this charm will request."""
        # Generate CN - try using the unit's FQDN -> HOSTNAME -> IP in that order
        unit_fqdn = socket.getfqdn()
        unit_hostname = socket.gethostname()
        unit_ip = socket.gethostbyname(unit_fqdn)
        for name in (unit_fqdn, unit_hostname, unit_ip):
            if len(name) <= 64:
                generated_common_name = name
                break
        common_name = self.config["frontend-cert-common-name"] or generated_common_name

        # Generate SANS_DNS - set to the unit hostname if not set in configuration
        sans_dns = self._dns_entries or [unit_fqdn]

        return CertificateRequestAttributes(
            common_name=common_name,
            sans_dns=frozenset(sans_dns),
        )

    def _update_certificates_required(self, provider_certificate: ProviderCertificate, private_key: PrivateKey) -> bool:
        """Check if the certificate or private key needs an update.

        This method retrieves the currently assigned certificate and private key associated with
        the charm's TLS relation. It checks whether the certificate or private key has changed
        or needs to be updated.

        Args:
            provider_certificate: the provider certificate given by the TLS provider.
            private_key: the private key given by the TLS provider.

        Returns:
            bool: True if either the certificate or the private key need to be updated,
                  False otherwise.
        """
        if not provider_certificate or not private_key:
            logger.debug("Certificate or private key is not available")
            return False

        certificate_update_required = self._is_certificate_update_required(provider_certificate.certificate)
        private_key_update_required = self._is_private_key_update_required(private_key)

        return certificate_update_required or private_key_update_required

    def _is_certificate_update_required(self, certificate: Certificate) -> bool:
        return self._get_existing_certificate() != certificate

    def _is_private_key_update_required(self, private_key: PrivateKey) -> bool:
        return self._get_existing_private_key() != private_key

    def _get_existing_certificate(self) -> Optional[Certificate]:
        return self._get_stored_certificate() if self._certificate_is_stored() else None

    def _get_existing_private_key(self) -> Optional[PrivateKey]:
        return self._get_stored_private_key() if self._private_key_is_stored() else None

    def _certificate_is_stored(self) -> bool:
        return self.container.exists(path=f"{CERTS_DIR_PATH}/{CERTIFICATE_NAME}")

    def _private_key_is_stored(self) -> bool:
        return self.container.exists(path=f"{CERTS_DIR_PATH}/{PRIVATE_KEY_NAME}")

    def _get_stored_certificate(self) -> Certificate:
        cert_string = str(self.container.pull(path=f"{CERTS_DIR_PATH}/{CERTIFICATE_NAME}").read())
        return Certificate.from_string(cert_string)

    def _get_stored_private_key(self) -> PrivateKey:
        key_string = str(self.container.pull(path=f"{CERTS_DIR_PATH}/{PRIVATE_KEY_NAME}").read())
        return PrivateKey.from_string(key_string)

    def _store_certificate(self, certificate: Certificate) -> None:
        """Store certificate in workload."""
        self.container.push(path=f"{CERTS_DIR_PATH}/{CERTIFICATE_NAME}", source=str(certificate))
        logger.info("Pushed certificate pushed to workload")

    def _store_private_key(self, private_key: PrivateKey) -> None:
        """Store private key in workload."""
        self.container.push(
            path=f"{CERTS_DIR_PATH}/{PRIVATE_KEY_NAME}",
            source=str(private_key),
        )
        logger.info("Pushed private key to workload")

    def _delete_certificate(self):
        """Delete certificate from workload container."""
        if self._certificate_is_stored():
            self.container.remove_path(path=f"{CERTS_DIR_PATH}/{CERTIFICATE_NAME}")
            logger.info("Removed certificate from workload")

    def _delete_private_key(self):
        """Delete private key from workload container."""
        if self._private_key_is_stored():
            self.container.remove_path(path=f"{CERTS_DIR_PATH}/{PRIVATE_KEY_NAME}")
            logger.info("Removed private key from workload")


if __name__ == "__main__":
    main.main(TemporalK8SCharm)
