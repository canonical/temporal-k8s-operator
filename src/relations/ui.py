# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Define the Temporal server ui relation."""

import logging

from ops import framework

logger = logging.getLogger(__name__)


class UI(framework.Object):
    """Client for ui:temporal relations."""

    def __init__(self, charm):
        """Construct.

        Args:
            charm: The charm to attach the hooks to.
        """
        super().__init__(charm, "ui")
        self.charm = charm
        # Observers are registered centrally in the charm's __init__.
        # This class is a stateless utility called by _reconcile.

    def _provide_server_status(self):
        """Provide server status to the UI charm.

        Called from _reconcile after validation passes, so the server is ready.
        """
        charm = self.charm

        ui_relations = charm.model.relations["ui"]
        if not ui_relations:
            logger.debug("ui:temporal: not providing server status: ui not ready")
            return
        for relation in ui_relations:
            logger.debug(f"ui:temporal: providing server status on relation {relation.id}")
            relation.data[charm.app].update({"server_status": "ready"})
