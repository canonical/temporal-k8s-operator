# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Define the Temporal server postgresql relation."""

import logging

from ops import framework

from literals import DB_NAME, DEFAULT_DB_DICT, VISIBILITY_DB_NAME

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
        # Observers are registered centrally in the charm's __init__.
        # This class is a stateless utility called by _reconcile.

    def update_db_relation_data_in_state(self) -> bool:
        """Update database data from relation into peer relation databag.

        Returns:
            True if the charm should update its pebble layer, False otherwise.
        """
        if not self.charm.unit.is_leader():
            return False

        if not self.charm._state.is_ready():
            return False

        if self.charm._state.database_connections is None:
            self.charm._state.database_connections = DEFAULT_DB_DICT

        should_update = False
        for rel_name in ["db", "visibility"]:
            if self.charm.model.get_relation(rel_name) is None:
                continue

            if rel_name == "db":
                relation_id = self.charm.db.relations[0].id
                relation_data = self.charm.db.fetch_relation_data()[relation_id]
            elif rel_name == "visibility":
                relation_id = self.charm.visibility.relations[0].id
                relation_data = self.charm.visibility.fetch_relation_data()[relation_id]
            else:
                return False

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
                "tls": relation_data.get("tls") == "True" or self.charm.config["db-tls-enabled"],
            }

            if None in (db_conn["user"], db_conn["password"]):
                continue

            fields_to_check = ["host", "user", "password", "tls"]
            database_connections = self.charm._state.database_connections or {}
            if any(
                (database_connections.get(rel_name) or {}).get(field, "") != db_conn[field] for field in fields_to_check
            ):
                should_update = True

            self._update_db_connections(rel_name, db_conn)

        return should_update

    def _update_db_connections(self, rel_name, db_conn):
        """Assign nested value in peer relation.

        Args:
            rel_name: Name of the relation to update.
            db_conn: Database connection dict.
        """
        if self.charm._state.database_connections is None:
            self.charm._state.database_connections = DEFAULT_DB_DICT

        database_connections = self.charm._state.database_connections
        database_connections[rel_name] = db_conn
        self.charm._state.database_connections = database_connections
