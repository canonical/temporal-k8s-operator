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

from charms.data_platform_libs.v0.database_requires import DatabaseRequires
from charms.data_platform_libs.v0.s3 import S3Requirer
from charms.grafana_k8s.v0.grafana_dashboard import GrafanaDashboardProvider
from charms.loki_k8s.v0.loki_push_api import LogProxyConsumer
from charms.nginx_ingress_integrator.v0.nginx_route import require_nginx_route
from charms.openfga_k8s.v1.openfga import OpenFGARequires
from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointProvider
from jinja2 import Environment, FileSystemLoader
from ops import main, pebble
from ops.charm import CharmBase
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, WaitingStatus
from ops.pebble import CheckStatus

from literals import (
    DB_NAME,
    LOG_FILE,
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
            self, relation_name="visibility", database_name=VISIBILITY_DB_NAME, extra_user_roles="admin"
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

        # Handle Ingress
        self._require_nginx_route()

        # Prometheus
        self._prometheus_scraping = MetricsEndpointProvider(
            self,
            relation_name="metrics-endpoint",
            jobs=[{"static_configs": [{"targets": [f"*:{PROMETHEUS_PORT}"]}]}],
            refresh_event=self.on.config_changed,
        )

        # Loki
        self._log_proxy = LogProxyConsumer(self, log_files=[LOG_FILE], relation_name="log-proxy")

        # Grafana
        self._grafana_dashboards = GrafanaDashboardProvider(self, relation_name="grafana-dashboard")

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

        if self._state.database_connections is None:
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

        config = render("config.jinja", context)
        container.push("/etc/temporal/config/charm.yaml", config, make_dirs=True)

        dynamic_context = {
            "GLOBAL_RPS_LIMIT": self.config["global-rps-limit"],
            "NAMESPACE_RPS_LIMIT": self.config["namespace-rps-limit"],
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


if __name__ == "__main__":
    main.main(TemporalK8SCharm)
