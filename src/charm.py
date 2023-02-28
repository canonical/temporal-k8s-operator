#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
#
# Learn more at: https://juju.is/docs/sdk

"""Charm definition and helpers."""

import logging
import os

# Nginx Ingress Integrator
from charms.nginx_ingress_integrator.v0.ingress import IngressRequires
from jinja2 import Environment, FileSystemLoader
from ops import framework, lib, main
from ops.charm import CharmBase
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, WaitingStatus

import relations
from log import log_event_handler

logger = logging.getLogger(__name__)
pgsql = lib.use("pgsql", 1, "postgresql-charmers@lists.launchpad.net")


def render(template_name, context):
    """Render the template with the given name using the given context dict."""
    charm_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
    loader = FileSystemLoader(os.path.join(charm_dir, "templates"))
    return Environment(loader=loader).get_template(template_name).render(**context)


class TemporalK8SCharm(CharmBase):
    """Temporal server charm."""

    _state = framework.StoredState()

    @property
    def external_hostname(self):
        return self.config["external-hostname"] or self.app.name

    def __init__(self, *args):
        super().__init__(*args)
        self.name = "temporal"

        # Handle basic charm lifecycle.
        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.temporal_pebble_ready, self._on_temporal_pebble_ready)
        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(self.on.restart_action, self._on_restart_action)

        # Handle db:pgsql and visibility:pgsql relations. The "db" and
        # "visibility" strings in this code block reflect the relation names.
        self._state.set_default(database_connections={"db": None, "visibility": None})
        self.db = pgsql.PostgreSQLClient(self, "db")
        self.framework.observe(self.db.on.database_relation_joined, self._on_database_relation_joined)
        self.framework.observe(self.db.on.master_changed, self._on_master_changed)
        self.visibility = pgsql.PostgreSQLClient(self, "visibility")
        self.framework.observe(self.visibility.on.database_relation_joined, self._on_database_relation_joined)
        self.framework.observe(self.visibility.on.master_changed, self._on_master_changed)

        # Handle admin:temporal relation.
        self._state.set_default(schema_ready=False)
        self.admin = relations.Admin(self)
        self.framework.observe(self.admin.on.schema_changed, self._on_schema_changed)

        # Handle Ingress
        self.ingress = IngressRequires(
            self,
            {
                "service-hostname": self.external_hostname,
                "service-name": self.app.name,
                "service-port": 7233,
            },
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

        Raise a ValueError if one of the databases is not connected yet.
        """
        # Copy key/value pairs in a new dict as self._state.database_connections
        # and its values (of type ops.framework.StoredDict) are not serializable.
        database_connections = {}
        for rel_name, db_conn in self._state.database_connections.items():
            if db_conn is None:
                raise ValueError(f"{rel_name}:pgsql relation: no database connection available")
            database_connections[rel_name] = dict(db_conn)
        return database_connections

    @log_event_handler(logger)
    def _on_install(self, event):
        """Install temporal."""
        self.unit.status = MaintenanceStatus("installing temporal")

    @log_event_handler(logger)
    def _on_temporal_pebble_ready(self, event):
        """Define and start temporal using the Pebble API."""
        self._update(event)

    @log_event_handler(logger)
    def _on_config_changed(self, event):
        """Handle configuration changes."""
        self.unit.status = WaitingStatus("configuring temporal")
        self.ingress.update_config({"service-hostname": self.external_hostname})
        self._update(event)

    @log_event_handler(logger)
    def _on_database_relation_joined(self, event: pgsql.DatabaseRelationJoinedEvent):
        """Handle joining a db:pgsql and visibility:pgsql relations."""
        dbname = f"{self.app.name}_{event.relation.name}"
        if self.model.unit.is_leader():
            # Provide requirements to the PostgreSQL server.
            self.unit.status = WaitingStatus("initializing database connection")
            event.database = dbname
        elif event.database != dbname:
            # Leader has not yet set requirements. Defer, in case this unit
            # becomes leader and needs to perform that operation.
            event.defer()

    @log_event_handler(logger)
    def _on_master_changed(self, event: pgsql.MasterChangedEvent):
        """Handle changes on the db:pgsql and visibility:pgsql relations."""
        dbname = f"{self.app.name}_{event.relation.name}"
        if event.database != dbname:
            # Leader has not yet set requirements. Wait until next event,
            # or risk connecting to an incorrect database.
            return

        self.unit.status = WaitingStatus(f"handling {event.relation.name} change")
        db_conn = None if event.master is None else dict(event.master.items())
        self._state.database_connections[event.relation.name] = db_conn
        self._update(event)

    @log_event_handler(logger)
    def _on_schema_changed(self, event):
        """Handle schema becoming ready."""
        self.unit.status = WaitingStatus("handling schema ready change")
        self._state.schema_ready = event.schema_ready
        self._update(event)

    @log_event_handler(logger)
    def _on_restart_action(self, event):
        """Restart the temporal server, even if there are no changes."""
        container = self.unit.get_container(self.name)

        logger.info("restarting temporal")
        self.unit.status = MaintenanceStatus("restarting temporal")
        container.restart(self.name)
        self.unit.status = ActiveStatus()

    def _validate(self):
        """Validate that configuration and relations are valid and ready.

        Raise a ValueError in case of problems.
        """
        # Validate config.
        valid_services = ("frontend", "history", "matching", "worker")
        for service in self.config["services"].split(","):
            if service not in valid_services:
                raise ValueError(f"error in services config: invalid service {service!r}")

        # Validate relations.
        self.database_connections()
        if not self._state.schema_ready:
            raise ValueError("admin:temporal relation: schema is not ready")

    def _update(self, event):
        """Update the Temporal server configuration and replan its execution."""
        try:
            self._validate()
        except ValueError as err:
            self.unit.status = BlockedStatus(str(err))
            return

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
