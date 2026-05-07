# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Define the Temporal server admin relation."""

import json
import logging

from log import log_event_handler

logger = logging.getLogger(__name__)


def provide_db_info(charm):
    """Provide DB info to the admin charm.

    Args:
        charm: The charm instance.
    """
    if not charm.unit.is_leader():
        return

    try:
        database_connections = charm.database_connections()
    except ValueError as err:
        logger.debug(f"admin:temporal: not providing database connections: {err}")
        return

    admin_relations = charm.model.relations["admin"]
    if not admin_relations:
        logger.debug("admin:temporal: not providing database connections: admin not ready")
        return
    for relation in admin_relations:
        logger.debug(f"admin:temporal: providing database connections on relation {relation.id}")
        relation.data[charm.app].update({"database_connections": json.dumps(database_connections)})
