# Copyright 2025 Canonical Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Relation management for temporal-host-info interface."""

import logging

from ops import CharmEvents, RelationChangedEvent, RelationJoinedEvent, framework
from ops.charm import CharmBase

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
        super().__init__(charm, 'host_info_provider')
        self.charm = charm
        self.port = port
        charm.framework.observe(
            charm.on.host_info_relation_joined, self._on_host_info_relation_changed
        )
        charm.framework.observe(
            charm.on.host_info_relation_changed, self._on_host_info_relation_changed
        )
        charm.framework.observe(charm.on.leader_elected, self._on_host_info_relation_changed)
        charm.framework.observe(charm.on.config_changed, self._on_host_info_relation_changed)

    def _on_host_info_relation_changed(self, event: RelationChangedEvent | RelationJoinedEvent):
        """Update relation data.

        :param: event: The relation event that triggered this handler.
        :type event: RelationChangedEvent | RelationJoinedEvent
        """
        logger.info('Handling temporal-host-info relation event')
        if self.charm.unit.is_leader() and 'frontend' in str(self.charm.config['services']):
            host = str(self.charm.config['external-hostname'])
            if binding := self.charm.model.get_binding(event.relation):
                host = host or str(binding.network.bind_address)
            event.relation.data[self.charm.app]['host'] = host
            event.relation.data[self.charm.app]['port'] = str(self.port)


class TemporalHostInfoRelationReadyEvent(framework.EventBase):
    """Event emitted when temporal-host-info relation is ready."""

    def __init__(
        self,
        handle: framework.Handle,
        host: str,
        port: int,
    ):
        super().__init__(handle)
        self.host = host
        self.port = port

    def snapshot(self) -> dict[str, str | int]:
        """Return a snapshot of the event."""
        return {'host': self.host, 'port': self.port}

    def restore(self, snapshot: dict[str, str | int]) -> None:
        """Restore the event from a snapshot."""
        self.host = snapshot['host']
        self.port = snapshot['port']


class TemporalHostInfoRequirerCharmEvents(CharmEvents):
    """List of events that the requirer charm can leverage."""

    host_info_available = framework.EventSource(TemporalHostInfoRelationReadyEvent)


class TemporalHostInfoRequirer(framework.Object):
    """A class for managing the temporal-host-info interface requirer.

    Track this relation in your charm with:

    .. code-block:: python

        self.host_info = TemporalHostInfoRequirer(self)
        # update container with new host info
        self.framework.observe(self.host_info.on.host_info_available, self._update)
    """

    def __init__(self, charm: CharmBase):
        """Create a new instance of the TemporalHostInfoProvider class.

        :param: charm: The charm that is using this interface.
        :type charm: CharmBase
        """
        super().__init__(charm, 'host_info_requirer')
        self.charm = charm
        self.on = TemporalHostInfoRequirerCharmEvents()  # type: ignore[reportAssignmentType]
        self.host: str | None = None
        self.port: int | None = None
        charm.framework.observe(
            charm.on.host_info_relation_joined, self._on_host_info_relation_changed
        )
        charm.framework.observe(
            charm.on.host_info_relation_changed, self._on_host_info_relation_changed
        )

    def _on_host_info_relation_changed(self, event: RelationChangedEvent):
        """Handle the relation joined/changed events.

        :param: event: The relation event that triggered this handler.
        :type event: RelationChangedEvent | RelationJoinedEvent
        """
        self.host = event.relation.data[event.relation.app]['host']
        self.port = int(event.relation.data[event.relation.app]['port'])
        self.on.host_info_available.emit(host=self.host, port=self.port)
