# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Manage the PostgreSQL relations used by Temporal."""

from ops.charm import RelationBrokenEvent

from literals import DB_NAME, VISIBILITY_DB_NAME


class Postgresql:
    """Read PostgreSQL connection data and preserve it for rolling upgrades."""

    def __init__(self, charm):
        """Construct the helper.

        Args:
            charm: The charm that owns the database requirers and peer relation.
        """
        self.charm = charm

    def database_connections(self):
        """Return connection info for the related databases.

        Raises:
            ValueError: If either database is not connected yet.

        Returns:
            The database connection info for persistence and visibility.
        """
        connections = {
            "db": self.database_connection("db"),
            "visibility": self.database_connection("visibility"),
        }

        if all(connection is None for connection in connections.values()):
            raise ValueError("database relation not ready")

        for relation_name, connection in connections.items():
            if connection is None:
                raise ValueError(f"{relation_name}:pgsql relation: no database connection available")
        return connections

    def database_connection(self, relation_name):
        """Return connection info read from a database relation.

        Args:
            relation_name: Name of the database relation, `db` or `visibility`.

        Returns:
            The connection info dict, or None if the relation has no usable connection yet.
        """
        charm = self.charm
        if charm.model.get_relation(relation_name) is None:
            return None

        requirer = charm.db if relation_name == "db" else charm.visibility
        relation_id = requirer.relations[0].id
        relation_data = requirer.fetch_relation_data()[relation_id]

        endpoints = relation_data.get("endpoints", "").split(",")
        primary_endpoint = endpoints[0].split(":")
        if len(primary_endpoint) < 2:
            return None

        connection = {
            "dbname": DB_NAME if relation_name == "db" else VISIBILITY_DB_NAME,
            "host": primary_endpoint[0],
            "port": primary_endpoint[1],
            "password": relation_data.get("password"),
            "user": relation_data.get("username"),
            "tls": relation_data.get("tls") == "True",
        }

        if None in (connection["user"], connection["password"]):
            return None
        return connection

    def reconcile_peer_state(self, event):
        """Keep legacy PostgreSQL connection data in peer data during rolling upgrades.

        A database without usable connection info keeps its previous value until its relation
        is gone.

        Args:
            event: The event being reconciled.
        """
        charm = self.charm
        stored = charm._peer_get("database_connections")
        current = stored if isinstance(stored, dict) else {}
        connections = {}
        for relation_name in ("db", "visibility"):
            connection = self.database_connection(relation_name)
            relation_gone = charm.model.get_relation(relation_name) is None or (
                isinstance(event, RelationBrokenEvent) and event.relation.name == relation_name
            )
            if relation_gone:
                connection = None
            elif connection is None:
                connection = current.get(relation_name)
            connections[relation_name] = connection

        if connections != stored and (stored is not None or any(connections.values())):
            charm._peer_set("database_connections", connections)
