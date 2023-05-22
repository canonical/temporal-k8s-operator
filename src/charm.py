#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
#
# Learn more at: https://juju.is/docs/sdk

"""Charm definition and helpers."""

import logging
import os

from charms.data_platform_libs.v0.database_requires import (
    DatabaseEvent,
    DatabaseRequires,
)
from charms.grafana_k8s.v0.grafana_dashboard import GrafanaDashboardProvider
from charms.loki_k8s.v0.loki_push_api import LogProxyConsumer
from charms.nginx_ingress_integrator.v0.nginx_route import require_nginx_route
from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointProvider
from jinja2 import Environment, FileSystemLoader
from ops import main
from ops.charm import CharmBase
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, WaitingStatus

import relations
from log import log_event_handler
from state import State

VALID_LOG_LEVELS = ["info", "debug", "warning", "error", "critical"]
LOG_FILE = "/var/log/temporal"
DB_NAME = "temporal-k8s_db"
VISIBILITY_DB_NAME = "temporal-k8s_visibility"

logger = logging.getLogger(__name__)

FRONTEND_PORT_GRPC = 7233
FRONTEND_PORT_HTTP = 6933
MATCHING_PORT_GRPC = 7235
MATCHING_PORT_HTTP = 6935
HISTORY_PORT_GRPC = 7234
HISTORY_PORT_HTTP = 6934
WORKER_PORT_GRPC = 7239
WORKER_PORT_HTTP = 6939
PROMETHEUS_PORT = 9090


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

        # Handle basic charm lifecycle.
        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.temporal_pebble_ready, self._on_temporal_pebble_ready)
        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(self.on.restart_action, self._on_restart_action)

        # Handle db:pgsql and visibility:pgsql relations. The "db" and
        # "visibility" strings in this code block reflect the relation names.
        self.db = DatabaseRequires(self, relation_name="db", database_name=DB_NAME)
        self.framework.observe(self.db.on.database_created, self._on_database_changed)
        self.framework.observe(self.db.on.endpoints_changed, self._on_database_changed)
        self.framework.observe(self.on.db_relation_broken, self._on_database_relation_broken)

        self.visibility = DatabaseRequires(self, relation_name="visibility", database_name=VISIBILITY_DB_NAME)
        self.framework.observe(self.visibility.on.database_created, self._on_database_changed)
        self.framework.observe(self.visibility.on.endpoints_changed, self._on_database_changed)
        self.framework.observe(self.on.visibility_relation_broken, self._on_database_relation_broken)

        # Handle admin:temporal relation.
        self.admin = relations.Admin(self)
        self.ui = relations.UI(self)
        self.framework.observe(self.admin.on.schema_changed, self._on_schema_changed)

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

    def _require_nginx_route(self):
        """Require nginx-route relation based on current configuration."""
        require_nginx_route(
            charm=self,
            service_hostname=self.external_hostname,
            service_name=self.app.name,
            service_port=FRONTEND_PORT_GRPC,
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
    def _on_database_changed(self, event: DatabaseEvent) -> None:
        """Handle database creation/change events.

        Args:
            event: The event triggered when the relation changed.
        """
        if not self._state.is_ready():
            event.defer()
            return

        if self.unit.is_leader():
            self.unit.status = WaitingStatus(f"handling {event.relation.name} change")
            self._update_db_connections(event)
            self._update(event)

    @log_event_handler(logger)
    def _on_database_relation_broken(self, event: DatabaseEvent) -> None:
        """Handle broken relations with the database.

        Args:
            event: The event triggered when the relation changed.
        """
        if not self._state.is_ready():
            event.defer()
            return

        if self.unit.is_leader():
            self._state.database_connections[event.relation.name] = None
            self._update(event)

    def _update_db_connections(self, event):
        """Assign nested value in peer relation.

        Args:
            event: The event triggered when the relation changed.
        """
        if self._state.database_connections is None:
            self._state.database_connections = {"db": None, "visibility": None}
        host, port = event.endpoints.split(",", 1)[0].split(":")
        name = event.relation.name

        db_conn = {
            "dbname": DB_NAME if name == "db" else VISIBILITY_DB_NAME,
            "host": host,
            "port": port,
            "password": event.password,
            "user": event.username,
        }

        database_connections = self._state.database_connections
        database_connections[name] = db_conn
        self._state.database_connections = database_connections

    @log_event_handler(logger)
    def _on_schema_changed(self, event):
        """Handle schema becoming ready.

        Args:
            event: The event triggered when the relation changed.
        """
        if not self._state.is_ready():
            event.defer()
            return

        if self.unit.is_leader():
            self.unit.status = WaitingStatus("handling schema ready change")
            self._state.schema_ready = event.schema_ready
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
        self.unit.status = ActiveStatus()

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
        valid_services = ("frontend", "history", "matching", "worker")
        for service in self.config["services"].split(","):
            if service not in valid_services:
                raise ValueError(f"error in services config: invalid service {service!r}")

        # Validate relations.
        self.database_connections()
        if not self._state.schema_ready:
            raise ValueError("admin:temporal relation: schema is not ready")

    def _open_service_ports(self):
        """Open the respective ports based on Temporal service."""
        services = self.config["services"]

        if "matching" in services:
            self.model.unit.open_port(protocol="tcp", port=MATCHING_PORT_GRPC)
            self.model.unit.open_port(protocol="tcp", port=MATCHING_PORT_HTTP)
        else:
            self.model.unit.close_port(protocol="tcp", port=MATCHING_PORT_GRPC)
            self.model.unit.close_port(protocol="tcp", port=MATCHING_PORT_HTTP)

        if "frontend" in services:
            self.model.unit.open_port(protocol="tcp", port=FRONTEND_PORT_GRPC)
            self.model.unit.open_port(protocol="tcp", port=FRONTEND_PORT_HTTP)
        else:
            self.model.unit.close_port(protocol="tcp", port=FRONTEND_PORT_GRPC)
            self.model.unit.close_port(protocol="tcp", port=FRONTEND_PORT_HTTP)

        if "history" in services:
            self.model.unit.open_port(protocol="tcp", port=HISTORY_PORT_GRPC)
            self.model.unit.open_port(protocol="tcp", port=HISTORY_PORT_HTTP)
        else:
            self.model.unit.close_port(protocol="tcp", port=HISTORY_PORT_GRPC)
            self.model.unit.close_port(protocol="tcp", port=HISTORY_PORT_HTTP)

        if "worker" in services:
            self.model.unit.open_port(protocol="tcp", port=WORKER_PORT_GRPC)
            self.model.unit.open_port(protocol="tcp", port=WORKER_PORT_HTTP)
        else:
            self.model.unit.close_port(protocol="tcp", port=WORKER_PORT_GRPC)
            self.model.unit.close_port(protocol="tcp", port=WORKER_PORT_HTTP)

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
                # TODO(kelkawi-a): do not assume the app is always deployed with this name.
                "PUBLIC_FRONTEND_ADDRESS": "temporal-k8s:7233",
            }
        )

        config = render("config.jinja", context)
        container.push("/etc/temporal/config/charm.yaml", config, make_dirs=True)

        logger.info("planning temporal execution")
        services = self.config["services"].split(",")
        services_args = " ".join(f"--service={service}" for service in services)
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
                }
            },
        }
        container.add_layer(self.name, pebble_layer, combine=True)
        container.replan()

        self.unit.status = ActiveStatus()


if __name__ == "__main__":
    main.main(TemporalK8SCharm)
