# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm library for the temporal-host-info relation interface.

This library provides the TemporalHostInfoProvider and TemporalHostInfoRequirer
classes for charms that need to share Temporal server connection details
(host, port and whether the frontend serves gRPC over TLS) over a Juju relation.

The `tls` field tells requirers which wire protocol the frontend speaks. It is
derived by the provider from whether frontend TLS is configured, and requirers
MUST honour it: dialling plaintext against a TLS frontend fails with
"error reading server preface: EOF", and the reverse fails the TLS handshake.

When `tls` is true, the requirer also needs the CA that issued the frontend
certificate in order to verify it. That CA is NOT carried on this relation;
it is distributed over the `certificate_transfer` interface, so that CA
rotation is handled by that library rather than reimplemented here.
"""

import logging
from typing import Callable, Union

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
LIBPATCH = 2

RELATION_NAME = "temporal-host-info"

logger = logging.getLogger(__name__)


class TemporalHostInfoProvider(Object):
    """A class for managing the temporal-host-info interface provider."""

    def __init__(
        self,
        charm: CharmBase,
        port: int,
        tls: Union[Callable[[], bool], bool] = False,
    ):
        """Create a new instance of the TemporalHostInfoProvider class.

        :param: charm: The charm that is using this interface.
        :type charm: CharmBase
        :param: port: The port number to provide to requirers. This is typically
            the 'frontend' service port.
        :type port: int
        :param: tls: Whether the frontend serves gRPC over TLS, or a callable
            returning it. Pass a callable when the value is not known at charm
            initialisation, which is the usual case since it depends on a
            certificates relation.
        :type tls: Union[Callable[[], bool], bool]
        """
        super().__init__(charm, "temporal_host_info_provider")
        self.charm = charm
        self.port = port
        self._get_tls = tls if callable(tls) else lambda: tls
        charm.framework.observe(charm.on[RELATION_NAME].relation_joined, self._on_host_info_relation_changed)
        charm.framework.observe(charm.on[RELATION_NAME].relation_changed, self._on_host_info_relation_changed)
        charm.framework.observe(charm.on.leader_elected, self._on_config_changed)
        charm.framework.observe(charm.on.config_changed, self._on_config_changed)

    def publish(self, relation: Relation | None = None) -> None:
        """Write the connection details to the relation databag(s).

        Call this whenever something the published data depends on changes --
        in particular when the frontend's TLS state changes -- since those
        events are not observed by this library.

        :param: relation: A single relation to update. All relations are
            updated when omitted.
        :type relation: Relation | None
        """
        if not self.charm.unit.is_leader() or "frontend" not in str(self.charm.config["services"]):
            return
        relations = [relation] if relation else self.charm.model.relations.get(RELATION_NAME, [])
        for rel in relations:
            app_data = rel.data[self.charm.app]
            app_data["host"] = self._resolve_host(rel)
            app_data["port"] = str(self.port)
            app_data["tls"] = str(self._get_tls()).lower()

    def _on_host_info_relation_changed(self, event: RelationChangedEvent | RelationJoinedEvent):
        """Update relation data.

        :param: event: The relation event that triggered this handler.
        :type event: RelationChangedEvent | RelationJoinedEvent
        """
        logger.debug("Handling temporal-host-info relation event")
        self.publish(event.relation)

    def _on_config_changed(self, event: ConfigChangedEvent | LeaderElectedEvent):
        """Update relation data on config change or leader election.

        :param: event: The event that triggered this handler.
        :type event: ConfigChangedEvent | LeaderElectedEvent
        """
        logger.debug("Config changed, updating temporal-host-info relation data")
        self.publish()

    def _resolve_host(self, relation: Relation | None = None) -> str:
        """Resolve the host requirers should dial.

        Prefers the configured external hostname, then the in-cluster service
        name. The binding address is only a last resort: it is a pod address,
        so it is unstable across restarts and cannot be covered by a DNS SAN,
        which means requirers cannot verify a TLS certificate against it.

        :param: relation: Unused; retained for backwards compatibility.
        :type relation: Relation | None
        :returns: The resolved host string.
        :rtype: str
        """
        host = str(self.charm.config["external-hostname"])
        if not host:
            host = f"{self.charm.app.name}.{self.charm.model.name}.svc.cluster.local"
        return host


class TemporalHostInfoChangedEvent(EventBase):
    """Event emitted when temporal-host-info relation data changes."""

    def __init__(
        self,
        handle: Handle,
        host: str,
        port: int,
        tls: bool = False,
    ):
        super().__init__(handle)
        self.host = host
        self.port = port
        self.tls = tls

    def snapshot(self) -> dict[str, str | int | bool]:
        """Return a snapshot of the event."""
        data = super().snapshot()
        data.update({"host": self.host, "port": self.port, "tls": self.tls})
        return data

    def restore(self, snapshot: dict[str, str | int | bool]) -> None:
        """Restore the event from a snapshot."""
        super().restore(snapshot)
        self.host = snapshot["host"]
        self.port = snapshot["port"]
        self.tls = bool(snapshot.get("tls", False))


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
            tls = self.host_info.tls

    When `tls` is true the frontend speaks gRPC over TLS and the requirer must
    dial accordingly, verifying the server certificate against the CA received
    over the `certificate_transfer` interface.
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

    @property
    def tls(self) -> bool:
        """Return whether the frontend serves gRPC over TLS.

        Defaults to False when the field is absent, which is the case against
        providers older than LIBPATCH 2. That matches their behaviour: those
        versions never served the frontend over TLS.
        """
        relation = self.relation
        if relation and relation.app:
            return relation.data[relation.app].get("tls", "false").lower() == "true"
        return False

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
        tls = app_data.get("tls", "false").lower() == "true"
        self.on.temporal_host_info_changed.emit(host=host, port=port, tls=tls)
