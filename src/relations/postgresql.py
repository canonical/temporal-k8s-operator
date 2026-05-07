# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Define the Temporal server postgresql relation — stateless utility."""

import logging

from literals import DB_NAME, DEFAULT_DB_DICT, VISIBILITY_DB_NAME

logger = logging.getLogger(__name__)


def read_db_relation_data(charm) -> None:
    """Read database relation data and persist to peer state.

    Safe to poll — DatabaseRequires stores data in relation databag.

    Args:
        charm: The charm instance.
    """
    if not charm.unit.is_leader():
        return

    if charm._state.database_connections is None:
        charm._state.database_connections = DEFAULT_DB_DICT

    for rel_name in ["db", "visibility"]:
        if charm.model.get_relation(rel_name) is None:
            continue

        if rel_name == "db":
            if not charm.db.relations:
                continue
            relation_id = charm.db.relations[0].id
            relation_data = charm.db.fetch_relation_data()[relation_id]
        elif rel_name == "visibility":
            if not charm.visibility.relations:
                continue
            relation_id = charm.visibility.relations[0].id
            relation_data = charm.visibility.fetch_relation_data()[relation_id]
        else:
            continue

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
            "tls": relation_data.get("tls") == "True" or charm.config["db-tls-enabled"],
        }

        if None in (db_conn["user"], db_conn["password"]):
            continue

        update_db_connections(charm, rel_name, db_conn)


def update_db_connections(charm, rel_name, db_conn):
    """Assign nested value in peer relation.

    Args:
        charm: The charm instance.
        rel_name: Name of the relation to update.
        db_conn: Database connection dict.
    """
    if charm._state.database_connections is None:
        charm._state.database_connections = DEFAULT_DB_DICT

    database_connections = charm._state.database_connections
    database_connections[rel_name] = db_conn
    charm._state.database_connections = database_connections
