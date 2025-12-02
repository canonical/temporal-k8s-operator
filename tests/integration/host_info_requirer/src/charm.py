# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""K8s charm for testing."""

import logging

import ops

from charms.temporal_k8s.v0 import temporal_host_info

logger = logging.getLogger(__name__)

CONTAINER = 'workload'


class Charm(ops.CharmBase):
    """Charm the application."""

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(self.on[CONTAINER].pebble_ready, self._configure)
        self.host_info = temporal_host_info.TemporalHostInfoRequirer(self)
        framework.observe(self.host_info.on.temporal_host_info_available, self._configure)

    def _configure(self, event: ops.EventBase):
        if self.host_info.host is None or self.host_info.port is None:
            self.unit.status = ops.WaitingStatus('Waiting for temporal-host-info relation data')
            return
        self.unit.status = ops.ActiveStatus(
            f'Temporal host: {self.host_info.host}, port: {self.host_info.port}'
        )


if __name__ == '__main__':  # pragma: nocover
    ops.main(Charm)
