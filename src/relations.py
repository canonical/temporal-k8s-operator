# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Define the Temporal server relations."""

import json
import logging

from ops import framework
from ops.charm import RelationEvent
from ops.model import ActiveStatus

from log import log_event_handler

logger = logging.getLogger(__name__)


class SchemaChangedEvent(RelationEvent):
    """The temporal schema has been created and it is ready.

    At this point it is possible to start the Temporal server.
    """

    def __init__(self, handle, relation, app, unit, schema_ready):
        """Construct.

        Args:
            handle: Defines a name for an object in the form of a hierarchical path.
            relation: The relation involved in the event.
            app: The remote application that has triggered the event.
            unit: The remote unit that has triggered the event.
            schema_ready: A flag to indicate whether the DB schema is ready or not.
        """
        super().__init__(handle, relation, app, unit)
        self.schema_ready = schema_ready

    def snapshot(self):
        """Snapshot getter.

        The framework uses pickle to serialize and restore event data and,
        without this method, the resulting event might not have the schema_ready
        attribute, potentially leading to many WTF moments.

        Returns:
           The event data that must be stored by the framework.
        """
        return (super().snapshot(), {"schema_ready": self.schema_ready})

    def restore(self, snapshot):
        """Restore from snapshot.

        Args:
            snapshot: snapshot to restore from.
        """
        sup, mine = snapshot
        super().restore(sup)
        self.schema_ready = mine["schema_ready"]


class _AdminEvents(framework.ObjectEvents):
    """Definition for admin:temporal schema changed events.

    Attrs:
        schema_changed: abc
    """

    schema_changed = framework.EventSource(SchemaChangedEvent)


class Admin(framework.Object):
    """Client for admin:temporal relations.

    Attrs:
        on: AdminEvents object.
    """

    on = _AdminEvents()

    def __init__(self, charm):
        """Construct.

        Args:
            charm: The charm to attach the hooks to.
        """
        super().__init__(charm, "admin")
        self.charm = charm
        charm.framework.observe(charm.on.admin_relation_joined, self._on_admin_relation_joined)
        charm.framework.observe(charm.on.admin_relation_changed, self._on_admin_relation_changed)
        charm.framework.observe(charm.db.on.master_changed, self._on_master_changed)
        charm.framework.observe(charm.visibility.on.master_changed, self._on_master_changed)

    @log_event_handler(logger)
    def _on_admin_relation_joined(self, event):
        """Handle new admin:temporal relations.

        Attempt to provide db info if already available to the admin unit.

        Args:
            event: The event triggered when the relation changed.
        """
        if not self.charm._state.is_ready():
            event.defer()
            return

        if self.charm.model.unit.is_leader():
            self._provide_db_info()

    @log_event_handler(logger)
    def _on_master_changed(self, event):
        """Handle changes on the db:pgsql relation.

        If an admin:temporal relation is established, then send database
        connection info to the remote unit.

        Args:
            event: The event triggered when the relation changed.
        """
        if not self.charm._state.is_ready():
            event.defer()
            return

        if self.charm.model.unit.is_leader():
            self._provide_db_info()

    @log_event_handler(logger)
    def _on_admin_relation_changed(self, event):
        """Handle changes on the admin:temporal relation.

        Report whether the schema is ready by emitting a schema_changed event.

        Args:
            event: The event triggered when the relation changed.
        """
        if not self.charm.model.unit.is_leader():
            return

        schema_ready = event.relation.data[event.app].get("schema_status") == "ready"
        logger.debug(f"admin:temporal: schema {'is ready' if schema_ready else 'is not ready'}")
        self.on.schema_changed.emit(relation=event.relation, app=event.app, unit=event.unit, schema_ready=schema_ready)

    def _provide_db_info(self):
        """Provide DB info to the admin charm."""
        charm = self.charm

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
        if self.charm.model.unit.is_leader():
            self._provide_server_status()

    def _provide_server_status(self):
        """Provide server status to the UI charm."""
        charm = self.charm
        server_status = charm.model.unit.status == ActiveStatus()

        ui_relations = charm.model.relations["ui"]
        if not ui_relations:
            logger.debug("ui:temporal: not providing server status: ui not ready")
            return
        for relation in ui_relations:
            logger.debug(f"ui:temporal: providing server status on relation {relation.id}")
            relation.data[charm.app].update({"server_status": "ready" if server_status else "blocked"})
