# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Define the Temporal server ui relation."""

import logging

from ops import framework
from ops.model import ActiveStatus

from log import log_event_handler

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
        charm.framework.observe(charm.on.ui_relation_joined, self._on_ui_relation_joined)
        charm.framework.observe(charm.on.ui_relation_changed, self._on_ui_relation_joined)

    @log_event_handler(logger)
    def _on_ui_relation_joined(self, event):
        """Handle new ui:temporal relations.

        Attempt to provide server status to the ui unit.

        Args:
            event: The event triggered when the relation changed.
        """
        if self.charm.unit.is_leader():
            self._provide_server_status()

    def _provide_server_status(self):
        """Provide server status to the UI charm."""
        charm = self.charm
        is_active = charm.model.unit.status == ActiveStatus() or charm.model.unit.status == ActiveStatus("auth enabled")

        ui_relations = charm.model.relations["ui"]
        if not ui_relations:
            logger.debug("ui:temporal: not providing server status: ui not ready")
            return
        for relation in ui_relations:
            logger.debug(f"ui:temporal: providing server status on relation {relation.id}")
            relation.data[charm.app].update({"server_status": "ready" if is_active else "blocked"})
