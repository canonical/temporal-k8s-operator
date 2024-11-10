# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Define the Temporal server postgresql relation."""

import logging

from ops import framework
from ops.model import WaitingStatus

from literals import DB_NAME, VISIBILITY_DB_NAME
from log import log_event_handler

logger = logging.getLogger(__name__)


class Postgresql(framework.Object):
    """Client for temporal:postgresql relations."""

    def __init__(self, charm):
        """Construct.

        Args:
            charm: The charm to attach the hooks to.
        """
        super().__init__(charm, "db")
        self.charm = charm

        # Handle db:pgsql and visibility:pgsql relations. The "db" and
        # "visibility" strings in this code block reflect the relation names.
        charm.framework.observe(charm.db.on.database_created, self._on_database_changed)
        charm.framework.observe(charm.db.on.endpoints_changed, self._on_database_changed)
        charm.framework.observe(charm.on.db_relation_broken, self._on_database_relation_broken)

        charm.framework.observe(charm.visibility.on.database_created, self._on_database_changed)
        charm.framework.observe(charm.visibility.on.endpoints_changed, self._on_database_changed)
        charm.framework.observe(charm.on.visibility_relation_broken, self._on_database_relation_broken)

    @log_event_handler(logger)
    def _on_database_changed(self, event) -> None:
        """Handle database creation/change events.

        Args:
            event: The event triggered when the relation changed.
        """
        if not self.charm.unit.is_leader():
            return

        if not self.charm._state.is_ready():
            event.defer()
            return

        self.charm.unit.status = WaitingStatus(f"handling {event.relation.name} change")
        if self.charm._state.database_connections is None:
            self.charm._state.database_connections = {"db": {}, "visibility": {}}

        self.update_db_relation_data_in_state()
        self.charm._update(event)

    @log_event_handler(logger)
    def _on_database_relation_broken(self, event) -> None:
        """Handle broken relations with the database.

        Args:
            event: The event triggered when the relation changed.
        """
        if not self.charm.unit.is_leader():
            return

        if not self.charm._state.is_ready():
            event.defer()
            return

        self._update_db_connections(event.relation.name, None)
        self.charm._update(event)

    def update_db_relation_data_in_state(self) -> bool:
        """Update database data from relation into peer relation databag.

        Returns:
            True if the charm should update its pebble layer, False otherwise.
        """
        if not self.charm.unit.is_leader():
            return False

        if not self.charm._state.is_ready():
            return False

        should_update = False
        for rel_name in ["db", "visibility"]:
            if self.charm.model.get_relation(rel_name) is None:
                continue

            if rel_name == "db":
                relation_id = self.charm.db.relations[0].id
                relation_data = self.charm.db.fetch_relation_data()[relation_id]
            else:
                relation_id = self.charm.visibility.relations[0].id
                relation_data = self.charm.visibility.fetch_relation_data()[relation_id]

            endpoints = relation_data.get("endpoints", "").split(",")
            if len(endpoints) < 1:
                continue

            primary_endpoint = endpoints[0].split(":")
            if len(primary_endpoint) < 2:
                continue

            db_conn = {
                "dbname": DB_NAME if rel_name == "db" else VISIBILITY_DB_NAME,
                "host": primary_endpoint[0],
                "port": primary_endpoint[1],
                "password": relation_data.get("password"),
                "user": relation_data.get("username"),
                "tls": relation_data.get("tls") or self.charm.config["db-tls-enabled"],
            }

            if None in (db_conn["user"], db_conn["password"]):
                continue

            fields_to_check = ["host", "user", "password", "tls"]
            if any(
                self.charm._state.database_connections.get(rel_name, {}).get(field, "") != db_conn[field]
                for field in fields_to_check
            ):
                should_update = True

            self._update_db_connections(rel_name, db_conn)
            self.charm.admin._provide_db_info()

        return should_update

    def _update_db_connections(self, rel_name, db_conn):
        """Assign nested value in peer relation.

        Args:
            rel_name: Name of the relation to update.
            db_conn: Database connection dict.
        """
        if self.charm._state.database_connections is None:
            self.charm._state.database_connections = {}

        database_connections = self.charm._state.database_connections
        database_connections[rel_name] = db_conn
        self.charm._state.database_connections = database_connections
