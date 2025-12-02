# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

from ops import (
    ConfigChangedEvent,
    Handle,
    LeaderElectedEvent,
    RelationChangedEvent,
    RelationJoinedEvent,
    framework,
)
from ops.charm import CharmBase
from ops.framework import EventBase, EventSource, ObjectEvents
from ops.model import ActiveStatus, Relation, WaitingStatus

# The unique Charmhub library identifier, never change it
LIBID = "024db27b47e546628c9ed7f26ddad6c8"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 1

RELATION_NAME = "temporal-host-info"

logger = logging.getLogger(__name__)


class TemporalHostInfoProvider(framework.Object):
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
        logger.info("Handling temporal-host-info relation event")
        if self.charm.unit.is_leader() and "frontend" in str(self.charm.config["services"]):
            host = str(self.charm.config["external-hostname"])
            if binding := self.charm.model.get_binding(event.relation):
                host = host or str(binding.network.bind_address)
            event.relation.data[self.charm.app]["host"] = host
            event.relation.data[self.charm.app]["port"] = str(self.port)

    def _on_config_changed(self, event: ConfigChangedEvent | LeaderElectedEvent):
        """Update relation data on config change."""
        logger.info("Config changed, updating temporal-host-info relation data")
        if self.charm.unit.is_leader() and "frontend" in str(self.charm.config["services"]):
            host = str(self.charm.config["external-hostname"])
            for relation in self.charm.model.relations.get("temporal-host-info", []):
                if binding := self.charm.model.get_binding(relation):
                    host = host or str(binding.network.bind_address)
                relation.data[self.charm.app]["host"] = host
                relation.data[self.charm.app]["port"] = str(self.port)


class TemporalHostInfoRelationReadyEvent(EventBase):
    """Event emitted when temporal-host-info relation is ready."""

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

    temporal_host_info_available = EventSource(TemporalHostInfoRelationReadyEvent)


class TemporalHostInfoRequirer(framework.Object):
    """A class for managing the temporal-host-info interface requirer.

    Track this relation in your charm with:

    .. code-block:: python

        self.host_info = TemporalHostInfoRequirer(self)
        # update container with new host info
        framework.observe(self.host_info.on.temporal_host_info_available, self._update)

        def _update(self, event):
            host = self.host_info.host
            port = self.host_info.port
    """

    on = TemporalHostInfoRequirerCharmEvents()  # type: ignore[reportAssignmentType]

    def __init__(self, charm: CharmBase):
        """Create a new instance of the TemporalHostInfoProvider class.

        :param: charm: The charm that is using this interface.
        :type charm: CharmBase
        """
        super().__init__(charm, "temporal_host_info_requirer")
        self.charm = charm
        charm.framework.observe(charm.on[RELATION_NAME].relation_joined, self._on_host_info_relation_changed)
        charm.framework.observe(charm.on[RELATION_NAME].relation_changed, self._on_host_info_relation_changed)

    @property
    def relations(self) -> list[Relation]:
        """Return the relations for this interface."""
        return self.charm.model.relations.get(RELATION_NAME, [])

    @property
    def host(self) -> str | None:
        """Return the host from the relation data."""
        for relation in self.relations:
            if relation and relation.app:
                return relation.data[relation.app].get("host", None)
        return None

    @property
    def port(self) -> int | None:
        """Return the port from the relation data."""
        for relation in self.relations:
            if relation and relation.app:
                port_str = relation.data[relation.app].get("port", None)
                if port_str is not None:
                    return int(port_str)
        return None

    def _on_host_info_relation_changed(self, event: RelationChangedEvent):
        """Handle the relation joined/changed events.

        :param: event: The relation event that triggered this handler.
        :type event: RelationChangedEvent | RelationJoinedEvent
        """
        try:
            host = event.relation.data[event.relation.app]["host"]
            port = int(event.relation.data[event.relation.app]["port"])
        except KeyError:
            self.charm.unit.status = WaitingStatus("Waiting for temporal-host-info provider")
            event.defer()
            return
        self.charm.unit.status = ActiveStatus()
        self.on.temporal_host_info_available.emit(host=host, port=port)
