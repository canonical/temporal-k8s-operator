# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm library for the temporal-host-info relation interface.

This library provides the TemporalHostInfoProvider and TemporalHostInfoRequirer
classes for charms that need to share Temporal server connection details
(host and port) over a Juju relation.
"""

import logging

from ops import (
    ConfigChangedEvent,
    Handle,
    LeaderElectedEvent,
    Object,
    RelationBrokenEvent,
    RelationChangedEvent,
    RelationJoinedEvent,
    TooManyRelatedAppsError,
)
from ops.charm import CharmBase
from ops.framework import EventBase, EventSource, ObjectEvents
from ops.model import Relation

# The unique Charmhub library identifier, never change it
LIBID = "024db27b47e546628c9ed7f26ddad6c8"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 1

RELATION_NAME = "temporal-host-info"

logger = logging.getLogger(__name__)


class TemporalHostInfoProvider(Object):
    """A class for managing the temporal-host-info interface provider."""

    def __init__(self, charm: CharmBase, port: int):
        """Create a new instance of the TemporalHostInfoProvider class.

        :param: charm: The charm that is using this interface.
        :type charm: CharmBase
        :param: port: The port number to provide to requirers. This is typically
            the 'frontend' service port.
        :type port: int
        """
        super().__init__(charm, "temporal_host_info_provider")
        self.charm = charm
        self.port = port
        charm.framework.observe(charm.on[RELATION_NAME].relation_joined, self._on_host_info_relation_changed)
        charm.framework.observe(charm.on[RELATION_NAME].relation_changed, self._on_host_info_relation_changed)
        charm.framework.observe(charm.on.leader_elected, self._on_config_changed)
        charm.framework.observe(charm.on.config_changed, self._on_config_changed)

    def _on_host_info_relation_changed(self, event: RelationChangedEvent | RelationJoinedEvent):
        """Update relation data.

        :param: event: The relation event that triggered this handler.
        :type event: RelationChangedEvent | RelationJoinedEvent
        """
        logger.debug("Handling temporal-host-info relation event")
        if not self.charm.unit.is_leader() or "frontend" not in str(self.charm.config["services"]):
            return
        host = self._resolve_host(event.relation)
        app_data = event.relation.data[self.charm.app]
        app_data["host"] = host
        app_data["port"] = str(self.port)

    def _on_config_changed(self, event: ConfigChangedEvent | LeaderElectedEvent):
        """Update relation data on config change or leader election.

        :param: event: The event that triggered this handler.
        :type event: ConfigChangedEvent | LeaderElectedEvent
        """
        logger.debug("Config changed, updating temporal-host-info relation data")
        if not self.charm.unit.is_leader() or "frontend" not in str(self.charm.config["services"]):
            return
        for relation in self.charm.model.relations.get(RELATION_NAME, []):
            host = self._resolve_host(relation)
            app_data = relation.data[self.charm.app]
            app_data["host"] = host
            app_data["port"] = str(self.port)

    def _resolve_host(self, relation: Relation) -> str:
        """Resolve host to external-hostname or relation binding address.

        :param: relation: The relation to resolve the host for.
        :type relation: Relation
        :returns: The resolved host string.
        :rtype: str
        """
        host = str(self.charm.config["external-hostname"])
        if not host:
            binding = self.charm.model.get_binding(relation)
            if binding:
                host = str(binding.network.bind_address)
        if not host:
            logger.warning("Could not resolve host: external-hostname is not set and no binding address is available")
        return host


class TemporalHostInfoChangedEvent(EventBase):
    """Event emitted when temporal-host-info relation data changes."""

    def __init__(
        self,
        handle: Handle,
        host: str,
        port: int,
    ):
        super().__init__(handle)
        self.host = host
        self.port = port

    def snapshot(self) -> dict[str, str | int]:
        """Return a snapshot of the event."""
        data = super().snapshot()
        data.update({"host": self.host, "port": self.port})
        return data

    def restore(self, snapshot: dict[str, str | int]) -> None:
        """Restore the event from a snapshot."""
        super().restore(snapshot)
        self.host = snapshot["host"]
        self.port = snapshot["port"]


class TemporalHostInfoRequirerCharmEvents(ObjectEvents):
    """List of events that the requirer charm can leverage."""

    temporal_host_info_changed = EventSource(TemporalHostInfoChangedEvent)
    # No data to snapshot/restore here, so we can just use EventBase
    temporal_host_info_unavailable = EventSource(EventBase)


class TemporalHostInfoRequirer(Object):
    """A class for managing the temporal-host-info interface requirer.

    Track this relation in your charm with:

    .. code-block:: python

        self.host_info = TemporalHostInfoRequirer(self)
        # update container with new host info
        framework.observe(self.host_info.on.temporal_host_info_changed, self._on_host_info_changed)

        def _on_host_info_changed(self, event):
            host = self.host_info.host
            port = self.host_info.port
    """

    on = TemporalHostInfoRequirerCharmEvents()  # type: ignore[reportAssignmentType]

    def __init__(self, charm: CharmBase):
        """Create a new instance of the TemporalHostInfoRequirer class.

        :param: charm: The charm that is using this interface.
        :type charm: CharmBase
        """
        super().__init__(charm, "temporal_host_info_requirer")
        self.charm = charm
        try:
            self.charm.model.get_relation(RELATION_NAME)
        except TooManyRelatedAppsError:
            raise RuntimeError(f"Multiple {RELATION_NAME} relations are not supported for requirers.")
        charm.framework.observe(charm.on[RELATION_NAME].relation_joined, self._on_host_info_relation_changed)
        charm.framework.observe(charm.on[RELATION_NAME].relation_changed, self._on_host_info_relation_changed)
        charm.framework.observe(charm.on[RELATION_NAME].relation_broken, self._on_host_info_relation_broken)

    @property
    def relation(self) -> Relation | None:
        """Return the relation for this interface, if any."""
        return self.charm.model.get_relation(RELATION_NAME)

    @property
    def host(self) -> str | None:
        """Return the host from the relation data."""
        relation = self.relation
        if relation and relation.app:
            return relation.data[relation.app].get("host", None)
        return None

    @property
    def port(self) -> int | None:
        """Return the port from the relation data."""
        relation = self.relation
        if relation and relation.app:
            port_str = relation.data[relation.app].get("port", None)
            if port_str is not None:
                return int(port_str)
        return None

    def _on_host_info_relation_broken(self, event: RelationBrokenEvent):
        """Handle the relation broken event.

        :param: event: The relation broken event that triggered this handler.
        :type event: RelationBrokenEvent
        """
        self.on.temporal_host_info_unavailable.emit()

    def _on_host_info_relation_changed(self, event: RelationChangedEvent | RelationJoinedEvent):
        """Handle the relation joined/changed events.

        :param: event: The relation event that triggered this handler.
        :type event: RelationChangedEvent | RelationJoinedEvent
        """
        app_data = event.relation.data[event.relation.app]
        try:
            host = app_data["host"]
            port = int(app_data["port"])
        except KeyError:
            return
        self.on.temporal_host_info_changed.emit(host=host, port=port)
