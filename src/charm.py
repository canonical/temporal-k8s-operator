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
from charms.loki_k8s.v1.loki_push_api import LogForwarder
from charms.nginx_ingress_integrator.v0.nginx_route import require_nginx_route
from charms.openfga_k8s.v1.openfga import OpenFGARequires
from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointProvider
from charms.tls_certificates_interface.v4.tls_certificates import (
    Certificate,
    CertificateRequestAttributes,
    Mode,
    PrivateKey,
    ProviderCertificate,
    TLSCertificatesRequiresV4,
)
from charms.traefik_k8s.v2.ingress import (
    IngressPerAppReadyEvent,
    IngressPerAppRequirer,
    IngressPerAppRevokedEvent,
)
from jinja2 import Environment, FileSystemLoader
from ops import EventBase, main, pebble
from ops.charm import CharmBase
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, WaitingStatus
from ops.pebble import CheckStatus

from literals import (
    DB_NAME,
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

    def set_active_unit_status(self):
        """Set active unit status depending on relations."""
        message = "auth enabled" if self.config["auth-enabled"] else ""
        self.unit.status = ActiveStatus(message)

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
        self._extra_context = {}
        self._dns_entries = [
            dns.strip() for dns in self.config.get("frontend-csr-sans-dns", "").split(",") if dns.strip()
        ]

        # Handle basic charm lifecycle.
        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.temporal_pebble_ready, self._on_temporal_pebble_ready)
        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(self.on.restart_action, self._on_restart_action)
        self.framework.observe(self.on.peer_relation_changed, self._on_peer_relation_changed)
        self.framework.observe(self.on.update_status, self._on_update_status)

        # Handle postgresql relation.
        self.db = DatabaseRequires(self, relation_name="db", database_name=DB_NAME, extra_user_roles="admin")
        self.visibility = DatabaseRequires(
            self,
            relation_name="visibility",
            database_name=VISIBILITY_DB_NAME,
            extra_user_roles="admin",
        )
        self.postgresql = Postgresql(self)

        # Handle admin and ui relations.
        self.admin = Admin(self)
        self.ui = UI(self)

        # Handle openfga relation
        self.openfga = OpenFGARequires(self, self.name)
        self.openfga_relation = OpenFGA(self)

        # Handle S3 integrator relation
        self.s3_client = S3Requirer(self, "s3-parameters")
        self.s3_relation = S3Integrator(self)

        # Handle Ingress (Nginx)
        self._require_nginx_route()

        # Prometheus
        self._prometheus_scraping = MetricsEndpointProvider(
            self,
            relation_name="metrics-endpoint",
            jobs=[{"static_configs": [{"targets": [f"*:{PROMETHEUS_PORT}"]}]}],
            refresh_event=self.on.config_changed,
        )

        # Loki
        self._log_forwarder = LogForwarder(self, relation_name="logging")

        # Grafana
        self._grafana_dashboards = GrafanaDashboardProvider(self, relation_name="grafana-dashboard")

        # Frontend TLS certificates
        # Only frontend TLS will be configured
        self.certificates = TLSCertificatesRequiresV4(
            charm=self,
            relationship_name=FRONTEND_CERTIFICATES_RELATION_NAME,
            certificate_requests=[self._get_certificate_request_attributes()],
            mode=Mode.UNIT,
            refresh_events=[self.on.upgrade_charm, self.on.config_changed],
        )
        self.framework.observe(self.certificates.on.certificate_available, self._handle_frontend_tls)
        self.framework.observe(self.on[FRONTEND_CERTIFICATES_RELATION_NAME].relation_joined, self._handle_frontend_tls)
        self.framework.observe(
            self.on[FRONTEND_CERTIFICATES_RELATION_NAME].relation_broken,
            self._on_frontend_certificates_relation_broken,
        )

        # Handle Ingress (Traefik)
        # Only handle ingress for the Frontend service
        # It is assumed that one application per deployment will be set to Frontend
        if self.model.get_relation("ingress"):
            if "frontend" not in self.config["services"]:
                self.unit.status = BlockedStatus("Not a frontend service, please remove ingress integration.")
            else:
                self.ingress = IngressPerAppRequirer(self, port=SERVICE_PORTS["frontend"]["grpc"], scheme=lambda: "h2c")
                self.framework.observe(self.ingress.on.ready, self._on_ingress_ready)
                self.framework.observe(self.ingress.on.revoked, self._on_ingress_revoked)

    # Frontend TLS handler
    def _handle_frontend_tls(self, event: EventBase):
        # Block if the unit is not configured as a frontend service but has the relation
        if "frontend" not in self.config["services"] and self.model.get_relation(FRONTEND_CERTIFICATES_RELATION_NAME):
            self.unit.status = BlockedStatus(
                f"Not a frontend service, please remove {FRONTEND_CERTIFICATES_RELATION_NAME} integration."
            )
            return

        # Pre-flight checks
        if not self.container.can_connect():
            return

        if not self._relation_created(FRONTEND_CERTIFICATES_RELATION_NAME):
            return

        # Fetch the assigned certificate and key
        provider_certificate, private_key = self.certificates.get_assigned_certificate(
            certificate_request=self._get_certificate_request_attributes()
        )

        # Set unit to WaitingStatus if certificate or key is not yet available
        if not provider_certificate or not private_key:
            logger.info("The certificate is not available yet.")
            self.unit.status = WaitingStatus("Waiting for certificates to be available")
            return

        # If either the certificate or key is outdated or missing, update both
        if self._update_certificates_required(provider_certificate, private_key):
            self._extra_context.update(FRONTEND_TLS_CONFIGURATION)
            self._store_certificate(certificate=provider_certificate.certificate)
            self._store_private_key(private_key=private_key)
            self._update(event)

    def _on_frontend_certificates_relation_broken(self, event: EventBase):
        """Handle the frontend-certificates relation broken."""
        if not self.container.can_connect():
            event.defer()
            return

        # These operations delete the files on upgrade
        # Certificates are updated on upgrade events, though
        self.unit.status = MaintenanceStatus("Removing certificates")
        self._delete_certificate()
        self._delete_private_key()
        self._update(event)                

    def _on_ingress_ready(self, event: IngressPerAppReadyEvent):
        logger.info("This app's ingress URL: %s", event.url)

    def _on_ingress_revoked(self, event: IngressPerAppRevokedEvent):
        logger.info("This app no longer has ingress")

    @log_event_handler(logger)
    def _on_peer_relation_changed(self, event):
        """Handle peer relation changes.

        Args:
            event: The event triggered when the peer relation changed.
        """
        if self.unit.is_leader():
            return

        self.unit.status = WaitingStatus("configuring temporal")
        self._update(event)

    def _require_nginx_route(self):
        """Require nginx-route relation based on current configuration."""
        if self.model.get_relation("ingress") and self.model.get_relation("nginx-route"):
            self.unit.status = BlockedStatus(
                "Only one ingress solution is allowed - remove the ingress or the nginx-route relation."
            )
            return
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
    def _on_install(self, event):
        """Install temporal.

        Args:
            event: The event triggered when the relation changed.
        """
        if self.unit.is_leader():
            self.unit.status = MaintenanceStatus("installing temporal")

    @log_event_handler(logger)
    def _on_temporal_pebble_ready(self, event):
        """Define and start temporal using the Pebble API.

        Args:
            event: The event triggered when the relation changed.
        """
        self._update(event)

    @log_event_handler(logger)
    def _on_config_changed(self, event):
        """Handle configuration changes.

        Args:
            event: The event triggered when the relation changed.
        """
        # Validate the frontend-csr-sans-dns configuration before proceeding
        invalid_dns = [dns for dns in self._dns_entries if not self._valid_dns(dns)]
        if invalid_dns:
            self.unit.status = BlockedStatus("Invalid frontend-csr-sans-dns, please correct the value(s).")
            logger.info(f"Invalid frontend-csr-sans-dns: {invalid_dns}")
            return

        self.unit.status = WaitingStatus("configuring temporal")
        self._update(event)

    @log_event_handler(logger)
    def _on_restart_action(self, event):
        """Restart the temporal server, even if there are no changes.

        Args:
            event: The event triggered when the relation changed.
        """
        container = self.unit.get_container(self.name)

        logger.info("restarting temporal")
        self.unit.status = MaintenanceStatus("restarting temporal")
        container.restart(self.name)
        self.set_active_unit_status()

    @log_event_handler(logger)
    def _on_update_status(self, event):
        """Handle `update-status` events.

        Args:
            event: The `update-status` event triggered at intervals.
        """
        try:
            self._validate()
        except ValueError:
            return

        should_update = self.postgresql.update_db_relation_data_in_state(event)
        if should_update:
            self._update(event)
            return

        container = self.unit.get_container(self.name)
        valid_pebble_plan = self._validate_pebble_plan(container)
        if not valid_pebble_plan:
            self._update(event)
            return

        check = container.get_check("up")
        if check.status != CheckStatus.UP:
            self.unit.status = MaintenanceStatus("Status check: DOWN")
            return

        self.unit.set_workload_version(WORKLOAD_VERSION)
        self.set_active_unit_status()
        if self.unit.is_leader():
            self.ui._provide_server_status()

    def _validate_pebble_plan(self, container):
        """Validate Temporal server pebble plan.

        Args:
            container: application container

        Returns:
            bool of pebble plan validity
        """
        try:
            plan = container.get_plan().to_dict()
            return bool(plan["services"][self.name]["on-check-failure"])
        except (KeyError, pebble.ConnectionError):
            return False

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

    def _update(self, event):
        """Update the Temporal server configuration and replan its execution.

        Args:
            event: The event triggered when the relation changed.
        """
        try:
            self._validate()
        except ValueError as err:
            self.unit.status = BlockedStatus(str(err))
            return

        if self.unit.is_leader():
            self._open_service_ports()

        container = self.unit.get_container(self.name)
        if not container.can_connect():
            event.defer()
            return

        logger.info("configuring temporal")
        options = {
            "log-level": "LOG_LEVEL",
        }
        context = {config_key: self.config[key] for key, config_key in options.items()}
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

        context.update(self._extra_context)
        config = render("config.jinja", context)
        container.push("/etc/temporal/config/charm.yaml", config, make_dirs=True)

        dynamic_context = {
            "GLOBAL_RPS_LIMIT": self.config["global-rps-limit"],
            "NAMESPACE_RPS_LIMIT": self.config["namespace-rps-limit"],
            "LONG_POLL_INTERVAL": self.config["long-poll-interval"],
        }
        dynamic_config = render("dynamic_config.jinja", dynamic_context)
        container.push("/etc/temporal/config/dynamicconfig/docker.yaml", dynamic_config, make_dirs=True)

        logger.info("planning temporal execution")
        services = self.config["services"].split(",")
        services_args = " ".join(f"--service={service}" for service in services)
        if ValidServiceTypes.FRONTEND.value in services:
            services_args += " --service=internal-frontend"

        pebble_layer = {
            "summary": "temporal server layer",
            "services": {
                self.name: {
                    "summary": "temporal server",
                    "command": "temporal-server --env charm start " + services_args,
                    "startup": "enabled",
                    "override": "replace",
                    # Including config values here so that a change in the
                    # config forces replanning to restart the service.
                    "environment": context,
                    "on-check-failure": {"up": "ignore"},
                }
            },
            "checks": {
                "up": {
                    "override": "replace",
                    "level": "alive",
                    "period": "300s",
                    # curl cluster health of internal-frontend service
                    "exec": {"command": "tctl --address=temporal-k8s:7236 cluster health"},
                }
            },
        }
        container.add_layer(self.name, pebble_layer, combine=True)
        container.replan()

        self.unit.status = MaintenanceStatus("replanning application")

    # Helpers for frontend TLS
    def _relation_created(self, relation_name: str) -> bool:
        return bool(self.model.relations.get(relation_name))

    def _certificate_is_available(self) -> bool:
        cert, key = self.certificates.get_assigned_certificate(
            certificate_request=self._get_certificate_request_attributes()
        )
        return bool(cert and key)

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
        # Generate common name - set to unit hostname if not set in configuration
        unit_domain_name = socket.getfqdn()
        common_name = self.config["frontend-csr-common-name"] or unit_domain_name

        # Generate SANS_DNS - set to the unit hostname if not set in configuration
        sans_dns = self._dns_entries or [unit_domain_name]

        return CertificateRequestAttributes(
            common_name=common_name,
            sans_dns=frozenset(sans_dns),
        )

    def _check_and_update_certificate(self) -> bool:
        """Check if the certificate or private key needs an update and perform the update.

        This method retrieves the currently assigned certificate and private key associated with
        the charm's TLS relation. It checks whether the certificate or private key has changed
        or needs to be updated. If an update is necessary, the new certificate or private key is
        stored.

        Returns:
            bool: True if either the certificate or the private key was updated, False otherwise.
        """
        provider_certificate, private_key = self.certificates.get_assigned_certificate(
            certificate_request=self._get_certificate_request_attributes()
        )
        if not provider_certificate or not private_key:
            logger.debug("Certificate or private key is not available")
            return False
        if certificate_update_required := self._is_certificate_update_required(provider_certificate.certificate):
            self._store_certificate(certificate=provider_certificate.certificate)
        if private_key_update_required := self._is_private_key_update_required(private_key):
            self._store_private_key(private_key=private_key)
        return certificate_update_required or private_key_update_required

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
