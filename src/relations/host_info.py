# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Define the host info relation."""

import logging

from ops import framework
from ops.charm import RelationEvent, CharmBase

from log import log_event_handler

logger = logging.getLogger(__name__)

class HostInfo(framework.Object):

    def __init__(self, charm: CharmBase, port: int):
        super().__init__(charm, "host_info")
        self.charm = charm
        self.port = port
        charm.framework.observe(charm.on.host_info_relation_joined, self._on_host_info_relation_joined)

    @log_event_handler(logger)
    def _on_host_info_relation_joined(self, event):
        if self.charm.unit.is_leader():
            for relation in self.charm.model.relations["host-info"]:
                data = {
                    "address": self.model.get_binding(relation).bind_address,
                    "port": self.port,
                    "hostname": self.charm.external_hostname,
                }
                relation.data[self.charm.app]["host_info"] = data
