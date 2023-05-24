# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Define the Temporal server postgresql relation."""

import logging

from charms.data_platform_libs.v0.database_requires import DatabaseEvent
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
    def _on_database_changed(self, event: DatabaseEvent) -> None:
        """Handle database creation/change events.

        Args:
            event: The event triggered when the relation changed.
        """
        if not self.charm._state.is_ready():
            event.defer()
            return

        if not self.charm.unit.is_leader():
            return
        
        self.charm.unit.status = WaitingStatus(f"handling {event.relation.name} change")
        if self.charm._state.database_connections is None:
            self.charm._state.database_connections = {"db": None, "visibility": None}
        host, port = event.endpoints.split(",", 1)[0].split(":")
        rel_name = event.relation.name

        db_conn = {
            "dbname": DB_NAME if rel_name == "db" else VISIBILITY_DB_NAME,
            "host": host,
            "port": port,
            "password": event.password,
            "user": event.username,
        }

        self._update_db_connections(rel_name, db_conn)

        self.charm._update(event)

    @log_event_handler(logger)
    def _on_database_relation_broken(self, event: DatabaseEvent) -> None:
        """Handle broken relations with the database.

        Args:
            event: The event triggered when the relation changed.
        """
        if not self.charm._state.is_ready():
            event.defer()
            return

        if self.charm.unit.is_leader():
            self._update_db_connections(event.relation.name, None)
            self.charm._update(event)

    def _update_db_connections(self, rel_name, db_conn):
        """Assign nested value in peer relation.

        Args:
            rel_name: Name of the relation to update.
            db_conn: Database connection dict.
        """
        database_connections = self.charm._state.database_connections
        database_connections[rel_name] = db_conn
        self.charm._state.database_connections = database_connections
