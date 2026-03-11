# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit tests for the temporal_host_info charm library."""

import dataclasses

import ops
import ops.testing
import pytest
from charms.temporal_k8s.v0.temporal_host_info import (
    TemporalHostInfoChangedEvent,
    TemporalHostInfoProvider,
    TemporalHostInfoRequirer,
)

RELATION_NAME = "temporal-host-info"
PROVIDER_PORT = 7233
BIND_ADDRESS = "10.0.0.1"
EXTERNAL_HOSTNAME = "temporal.example.com"


# Minimal provider charm
class ProviderCharm(ops.CharmBase):
    """Minimal charm for testing TemporalHostInfoProvider.

    Attributes:
        META: Charm metadata defining the temporal-host-info relation.
        CONFIG: Charm config options for services and external-hostname.
    """

    META = {
        "name": "provider-charm",
        "provides": {RELATION_NAME: {"interface": RELATION_NAME}},
    }
    CONFIG = {
        "options": {
            "services": {"type": "string", "default": "frontend"},
            "external-hostname": {"type": "string", "default": ""},
        }
    }

    def __init__(self, framework: ops.Framework):
        """Initialize the provider charm and its TemporalHostInfoProvider.

        Args:
            framework: The charm framework.
        """
        super().__init__(framework)
        self.host_info = TemporalHostInfoProvider(self, port=PROVIDER_PORT)


# Minimal requirer charm
class RequirerCharm(ops.CharmBase):
    """Minimal charm for testing TemporalHostInfoRequirer.

    Attributes:
        META: Charm metadata defining the temporal-host-info relation.
    """

    META = {
        "name": "requirer-charm",
        "requires": {RELATION_NAME: {"interface": RELATION_NAME, "limit": 1}},
    }

    def __init__(self, framework: ops.Framework):
        """Initialize the requirer charm and its TemporalHostInfoRequirer.

        Args:
            framework: The charm framework.
        """
        super().__init__(framework)
        self.host_info = TemporalHostInfoRequirer(self)
        self.received_host_info_changed: list[ops.EventBase] = []
        self.received_host_info_broken: list[ops.EventBase] = []
        framework.observe(self.host_info.on.temporal_host_info_changed, self._on_changed)
        framework.observe(self.host_info.on.temporal_host_info_broken, self._on_broken)

    def _on_changed(self, event: ops.EventBase) -> None:
        """Record temporal_host_info_changed events for testing."""
        self.received_host_info_changed.append(event)

    def _on_broken(self, event: ops.EventBase) -> None:
        """Record temporal_host_info_broken events for testing."""
        self.received_host_info_broken.append(event)


# Provider fixtures
@pytest.fixture
def provider_context():
    """ops.testing.Context for the provider charm."""
    return ops.testing.Context(
        charm_type=ProviderCharm,
        meta=ProviderCharm.META,
        config=ProviderCharm.CONFIG,
    )


@pytest.fixture
def provider_relation():
    """A temporal-host-info relation on the provider side (no remote data needed)."""
    return ops.testing.Relation(RELATION_NAME)


@pytest.fixture
def provider_network():
    """Simulated network binding for temporal-host-info endpoint."""
    return ops.testing.Network(
        RELATION_NAME,
        bind_addresses=[
            ops.testing.BindAddress(
                addresses=[ops.testing.Address(value=BIND_ADDRESS)],
            )
        ],
    )


@pytest.fixture
def provider_state_with_ext_hostname(provider_relation):
    """Provider state: leader, frontend service, external-hostname set."""
    return ops.testing.State(
        leader=True,
        config={"services": "frontend", "external-hostname": EXTERNAL_HOSTNAME},
        relations=[provider_relation],
    )


@pytest.fixture
def provider_state_no_ext_hostname(provider_relation, provider_network):
    """Provider state: leader, frontend service, no external-hostname."""
    return ops.testing.State(
        leader=True,
        config={"services": "frontend", "external-hostname": ""},
        relations=[provider_relation],
        networks={provider_network},
    )


# Requirer fixtures
@pytest.fixture
def requirer_context():
    """ops.testing.Context for the requirer charm."""
    return ops.testing.Context(
        charm_type=RequirerCharm,
        meta=RequirerCharm.META,
    )


@pytest.fixture
def requirer_relation_with_data():
    """A temporal-host-info relation with provider data already populated."""
    return ops.testing.Relation(
        RELATION_NAME,
        remote_app_data={"host": EXTERNAL_HOSTNAME, "port": str(PROVIDER_PORT)},
    )


@pytest.fixture
def requirer_relation_no_data():
    """A temporal-host-info relation with no provider data yet."""
    return ops.testing.Relation(RELATION_NAME, remote_app_data={})


# Provider tests
class TestTemporalHostInfoProvider:
    """Unit tests for TemporalHostInfoProvider."""

    def test_provider_writes_external_hostname_on_relation_joined(
        self,
        provider_context,
        provider_state_with_ext_hostname,
        provider_relation,
    ):
        """Provider writes external-hostname and port into relation data on relation_joined."""
        state_out = provider_context.run(
            provider_context.on.relation_joined(provider_relation),
            provider_state_with_ext_hostname,
        )

        relation_out = state_out.get_relations(RELATION_NAME)[0]
        assert relation_out.local_app_data["host"] == EXTERNAL_HOSTNAME
        assert relation_out.local_app_data["port"] == str(PROVIDER_PORT)

    def test_provider_writes_bind_address_when_no_external_hostname_on_relation_joined(
        self,
        provider_context,
        provider_state_no_ext_hostname,
        provider_relation,
    ):
        """Provider falls back to binding IP when external-hostname is empty."""
        state_out = provider_context.run(
            provider_context.on.relation_joined(provider_relation),
            provider_state_no_ext_hostname,
        )

        relation_out = state_out.get_relations(RELATION_NAME)[0]
        assert relation_out.local_app_data["host"] == BIND_ADDRESS
        assert relation_out.local_app_data["port"] == str(PROVIDER_PORT)

    def test_provider_noop_when_not_leader_on_relation_joined(
        self,
        provider_context,
        provider_state_with_ext_hostname,
        provider_relation,
    ):
        """Provider does not write relation data when unit is not the leader."""
        non_leader_state = dataclasses.replace(provider_state_with_ext_hostname, leader=False)

        state_out = provider_context.run(
            provider_context.on.relation_joined(provider_relation),
            non_leader_state,
        )

        relation_out = state_out.get_relations(RELATION_NAME)[0]
        assert relation_out.local_app_data == {}

    def test_provider_noop_when_frontend_not_in_services_on_relation_joined(
        self,
        provider_context,
        provider_relation,
    ):
        """Provider does not write relation data when frontend service is not enabled."""
        state = ops.testing.State(
            leader=True,
            config={"services": "history,matching", "external-hostname": EXTERNAL_HOSTNAME},
            relations=[provider_relation],
        )

        state_out = provider_context.run(
            provider_context.on.relation_joined(provider_relation),
            state,
        )

        relation_out = state_out.get_relations(RELATION_NAME)[0]
        assert relation_out.local_app_data == {}

    @pytest.mark.parametrize("event_name", ["config_changed", "leader_elected"])
    def test_provider_updates_all_relations_on_config_or_leader_event(
        self,
        provider_context,
        provider_network,
        event_name,
    ):
        """Provider updates all existing relations on config_changed and leader_elected.

        Both events share the same handler, so both must push updated data to all requirers.
        """
        relation_a = ops.testing.Relation(RELATION_NAME)
        relation_b = ops.testing.Relation(RELATION_NAME)
        state = ops.testing.State(
            leader=True,
            config={"services": "frontend", "external-hostname": EXTERNAL_HOSTNAME},
            relations=[relation_a, relation_b],
            networks={provider_network},
        )
        event = getattr(provider_context.on, event_name)()

        state_out = provider_context.run(event, state)

        for rel in state_out.get_relations(RELATION_NAME):
            assert rel.local_app_data["host"] == EXTERNAL_HOSTNAME
            assert rel.local_app_data["port"] == str(PROVIDER_PORT)

    def test_provider_noop_when_not_leader_on_config_changed(
        self,
        provider_context,
        provider_relation,
    ):
        """Provider does not update relation data on config_changed when not leader."""
        state = ops.testing.State(
            leader=False,
            config={"services": "frontend", "external-hostname": EXTERNAL_HOSTNAME},
            relations=[provider_relation],
        )

        state_out = provider_context.run(provider_context.on.config_changed(), state)

        relation_out = state_out.get_relations(RELATION_NAME)[0]
        assert relation_out.local_app_data == {}


# Requirer tests
class TestTemporalHostInfoRequirer:
    """Unit tests for TemporalHostInfoRequirer."""

    def test_requirer_emits_changed_event_when_data_present(
        self,
        requirer_context,
        requirer_relation_with_data,
    ):
        """Requirer emits temporal_host_info_changed when host and port are in relation data."""
        state = ops.testing.State(
            leader=True,
            relations=[requirer_relation_with_data],
        )

        with requirer_context(requirer_context.on.relation_changed(requirer_relation_with_data), state) as manager:
            charm = manager.charm
            manager.run()

        assert len(charm.received_host_info_changed) == 1
        event = charm.received_host_info_changed[0]
        assert isinstance(event, TemporalHostInfoChangedEvent)
        assert event.host == EXTERNAL_HOSTNAME
        assert event.port == PROVIDER_PORT

    def test_requirer_noop_when_data_missing(
        self,
        requirer_context,
        requirer_relation_no_data,
    ):
        """Requirer does not emit changed event when host/port not yet in relation data."""
        state = ops.testing.State(
            leader=True,
            relations=[requirer_relation_no_data],
        )

        with requirer_context(requirer_context.on.relation_changed(requirer_relation_no_data), state) as manager:
            charm = manager.charm
            manager.run()

        assert len(charm.received_host_info_changed) == 0

    def test_requirer_emits_broken_event_on_relation_broken(
        self,
        requirer_context,
        requirer_relation_with_data,
    ):
        """Requirer emits temporal_host_info_broken when relation is removed."""
        state = ops.testing.State(
            leader=True,
            relations=[requirer_relation_with_data],
        )

        with requirer_context(requirer_context.on.relation_broken(requirer_relation_with_data), state) as manager:
            charm = manager.charm
            manager.run()

        assert len(charm.received_host_info_broken) == 1

    def test_requirer_raises_on_multiple_relations(self, requirer_context):
        """Requirer raises RuntimeError if more than one temporal-host-info relation exists."""
        state = ops.testing.State(
            leader=True,
            relations=[
                ops.testing.Relation(RELATION_NAME),
                ops.testing.Relation(RELATION_NAME),
            ],
        )

        with pytest.raises(RuntimeError, match="Multiple.*not supported"):
            requirer_context.run(requirer_context.on.config_changed(), state)

    def test_requirer_host_property_returns_none_when_no_relation(
        self,
        requirer_context,
    ):
        """Requirer host property returns None when no relation is present."""
        state = ops.testing.State(leader=True, relations=[])

        with requirer_context(requirer_context.on.config_changed(), state) as manager:
            charm = manager.charm
            manager.run()

        assert charm.host_info.host is None
        assert charm.host_info.port is None

    def test_requirer_host_property_returns_values_when_data_present(
        self,
        requirer_context,
        requirer_relation_with_data,
    ):
        """Requirer host and port properties return correct values from relation data."""
        state = ops.testing.State(
            leader=True,
            relations=[requirer_relation_with_data],
        )

        with requirer_context(requirer_context.on.config_changed(), state) as manager:
            charm = manager.charm
            manager.run()

        assert charm.host_info.host == EXTERNAL_HOSTNAME
        assert charm.host_info.port == PROVIDER_PORT
