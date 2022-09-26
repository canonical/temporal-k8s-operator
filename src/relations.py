# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Define the Temporal server relations."""

import logging

from ops import framework
from ops.charm import RelationEvent

from log import log_event_handler

logger = logging.getLogger(__name__)


class SchemaChangedEvent(RelationEvent):
    """The temporal schema has been created and it is ready.

    At this point it is possible to start the Temporal server.
    """

    def __init__(self, handle, relation, app, unit, schema_ready):
        super().__init__(handle, relation, app, unit)
        self.schema_ready = schema_ready

    def snapshot(self):
        """Return the event data that must be stored by the framework.

        The framework uses pickle to serialize and restore event data and,
        without this method, the resulting event might not have the schema_ready
        attribute, potentially leading to many WTF moments.
        """
        return (super().snapshot(), {"schema_ready": self.schema_ready})

    def restore(self, snapshot):
        """Restore from snapshot."""
        sup, mine = snapshot
        super().restore(sup)
        self.schema_ready = mine["schema_ready"]


class _AdminEvents(framework.ObjectEvents):

    schema_changed = framework.EventSource(SchemaChangedEvent)


class Admin(framework.Object):
    """Client for admin:temporal relations.

    It must be initialized passing the charm and a function returning connection
    info as a dict with dbname, host, port, user and password keys.
    """

    on = _AdminEvents()

    def __init__(self, charm, get_db_conn):
        super().__init__(charm, "admin")
        self.charm = charm
        self._get_db_conn = get_db_conn
        charm.framework.observe(charm.on.admin_relation_joined, self._on_admin_relation_joined)
        charm.framework.observe(charm.db.on.master_changed, self._on_master_changed)

    @log_event_handler(logger)
    def _on_admin_relation_joined(self, event):
        """Handle new admin:temporal relations.

        Attempt to provide db info if already available to the admin unit.
        """
        if self.charm.model.unit.is_leader():
            self._provide_db_info()

    @log_event_handler(logger)
    def _on_master_changed(self, event):
        """Handle changes on the db:pgsql relation.

        If an admin:temporal relation is established, then send database
        connection info to the remote unit.
        """
        if self.charm.model.unit.is_leader() and event.database == self.charm.app.name:
            # The unit is the leader and the database is ready.
            self._provide_db_info()

    @log_event_handler(logger)
    def _on_admin_relation_changed(self, event):
        """Handle changes on the admin:temporal relation.

        Report whether the schema is ready by emitting a schema_changed event.
        """
        if not self.charm.model.unit.is_leader():
            return

        schema_ready = event.relation.data[event.app].get("schema_ready")
        logger.debug(f"admin:temporal: schema {'is ready' if schema_ready else 'is not ready'}")
        self.on.schema_changed.emit(relation=event.relation, app=event.app, unit=event.unit, schema_ready=schema_ready)

    def _provide_db_info(self):
        db_conn = self._get_db_conn()
        if db_conn is None:
            logger.debug("admin:temporal: not providing db conn: database not ready")
            return
        charm = self.charm
        admin_relations = charm.model.relations["admin"]
        if not admin_relations:
            logger.debug("admin:temporal: not providing db conn: admin not ready")
            return
        for relation in admin_relations:
            logger.debug(f"admin:temporal: providing db conn on relation {relation.id}")
            relation.data[charm.app].update({"db_conn": db_conn})
