# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Define the Temporal server admin relation."""

import json
import logging

from ops import framework

logger = logging.getLogger(__name__)


class Admin(framework.Object):
    """Client for admin:temporal relations."""

    def __init__(self, charm):
        """Construct.

        Args:
            charm: The charm to attach the hooks to.
        """
        super().__init__(charm, "admin")
        self.charm = charm
        # Observers are registered centrally in the charm's __init__.
        # This class is a stateless utility called by _reconcile.

    def _provide_db_info(self):
        """Provide DB info to the admin charm."""
        charm = self.charm

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
