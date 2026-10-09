# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit tests for the temporal_host_info charm library."""

import dataclasses
from typing import Callable, Union

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
SERVICE_FQDN = "provider-charm.test-model.svc.cluster.local"


# Minimal provider charm
class ProviderCharm(ops.CharmBase):
    """Minimal charm for testing TemporalHostInfoProvider.

    Attributes:
        META: Charm metadata defining the temporal-host-info relation.
        CONFIG: Charm config options for services and external-hostname.
        TLS: Value passed as the provider's `tls`; the library default when False.
        HOST: Host passed to the provider; None publishes the binding address.
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
    TLS: Union[Callable[[], bool], bool] = False
    HOST: Union[Callable[[], str], str, None] = None

    def __init__(self, framework: ops.Framework):
        """Initialize the provider charm and its TemporalHostInfoProvider.

        Args:
            framework: The charm framework.
        """
        super().__init__(framework)
        self.host_info = TemporalHostInfoProvider(self, port=PROVIDER_PORT, tls=self.provider_tls())

    def provider_tls(self) -> Union[Callable[[], bool], bool]:
        """Return the value passed as the provider's `tls`.

        Returns:
            The class's TLS attribute.
        """
        return self.TLS


class TlsProviderCharm(ProviderCharm):
    """Provider charm whose frontend serves TLS, passed as a plain value.

    Attributes:
        TLS: Always True.
    """

    TLS = True


class CallableTlsProviderCharm(ProviderCharm):
    """Provider charm that passes `tls` as a callable, as temporal-k8s does.

    The callable reads `tls_enabled` on the charm, so tests can change it after
    the charm is initialised and check that the provider evaluates it when it
    publishes rather than when it is constructed.

    Attributes:
        tls_enabled: The value the `tls` callable returns.
    """

    tls_enabled = False

    def provider_tls(self) -> Callable[[], bool]:
        """Return a callable that reads `tls_enabled` when the provider publishes.

        Returns:
            The `tls` callable.
        """
        return lambda: self.tls_enabled
        self.host_info = TemporalHostInfoProvider(self, port=PROVIDER_PORT, host=self.HOST)


class HostProviderCharm(ProviderCharm):
    """Provider charm that supplies the host to publish.

    Attributes:
        HOST: The host passed to the provider.
    """

    HOST = SERVICE_FQDN


class CallableHostProviderCharm(ProviderCharm):
    """Provider charm that supplies the host to publish as a callable.

    Attributes:
        HOST: A callable returning the host passed to the provider.
    """

    HOST = staticmethod(lambda: SERVICE_FQDN)


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
        self.received_host_info_unavailable: list[ops.EventBase] = []
        framework.observe(self.host_info.on.temporal_host_info_changed, self._on_changed)
        framework.observe(self.host_info.on.temporal_host_info_unavailable, self._on_unavailable)

    def _on_changed(self, event: ops.EventBase) -> None:
        """Record temporal_host_info_changed events for testing."""
        self.received_host_info_changed.append(event)

    def _on_unavailable(self, event: ops.EventBase) -> None:
        """Record temporal_host_info_unavailable events for testing."""
        self.received_host_info_unavailable.append(event)


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

    @pytest.mark.parametrize("charm_type", [HostProviderCharm, CallableHostProviderCharm])
    def test_provider_writes_supplied_host_on_relation_joined(
        self,
        charm_type,
        provider_state_with_ext_hostname,
        provider_relation,
    ):
        """Provider writes the supplied host (value or callable) and ignores external-hostname."""
        context = ops.testing.Context(charm_type=charm_type, meta=ProviderCharm.META, config=ProviderCharm.CONFIG)

        state_out = context.run(
            context.on.relation_joined(provider_relation),
            provider_state_with_ext_hostname,
        )

        relation_out = state_out.get_relations(RELATION_NAME)[0]
        assert relation_out.local_app_data["host"] == SERVICE_FQDN
        assert relation_out.local_app_data["port"] == str(PROVIDER_PORT)

    def test_provider_ignores_external_hostname_without_supplied_host(
        self,
        provider_context,
        provider_relation,
        provider_network,
    ):
        """Provider never publishes external-hostname, which is for nginx-route only."""
        state = ops.testing.State(
            leader=True,
            config={"services": "frontend", "external-hostname": EXTERNAL_HOSTNAME},
            relations=[provider_relation],
            networks={provider_network},
        )

        state_out = provider_context.run(provider_context.on.relation_joined(provider_relation), state)

        relation_out = state_out.get_relations(RELATION_NAME)[0]
        assert relation_out.local_app_data["host"] == BIND_ADDRESS

    def test_provider_writes_bind_address_when_no_external_hostname_on_relation_joined(
        self,
        provider_context,
        provider_state_no_ext_hostname,
        provider_relation,
    ):
        """Provider falls back to binding IP when no host is supplied."""
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
            assert rel.local_app_data["host"] == BIND_ADDRESS
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

    def test_provider_writes_tls_false_by_default(
        self,
        provider_context,
        provider_state_with_ext_hostname,
        provider_relation,
    ):
        """Provider publishes tls=false when the charm doesn't pass `tls`."""
        state_out = provider_context.run(
            provider_context.on.relation_joined(provider_relation),
            provider_state_with_ext_hostname,
        )

        assert state_out.get_relations(RELATION_NAME)[0].local_app_data["tls"] == "false"

    def test_provider_writes_tls_true(self, provider_state_with_ext_hostname, provider_relation):
        """Provider publishes tls=true when the charm passes `tls=True`."""
        context = ops.testing.Context(TlsProviderCharm, meta=ProviderCharm.META, config=ProviderCharm.CONFIG)

        state_out = context.run(context.on.relation_joined(provider_relation), provider_state_with_ext_hostname)

        assert state_out.get_relations(RELATION_NAME)[0].local_app_data["tls"] == "true"

    @pytest.mark.parametrize("tls_enabled, expected", [(False, "false"), (True, "true")])
    def test_provider_evaluates_tls_callable_when_publishing(
        self,
        provider_state_with_ext_hostname,
        provider_relation,
        tls_enabled,
        expected,
    ):
        """Provider calls a `tls` callable when it publishes, not when it is constructed.

        temporal-k8s passes a callable because TLS depends on the certificates
        relation, which isn't known at charm init.
        """
        context = ops.testing.Context(CallableTlsProviderCharm, meta=ProviderCharm.META, config=ProviderCharm.CONFIG)

        with context(context.on.relation_joined(provider_relation), provider_state_with_ext_hostname) as manager:
            # Changed after the provider was constructed with the callable.
            manager.charm.tls_enabled = tls_enabled
            state_out = manager.run()

        assert state_out.get_relations(RELATION_NAME)[0].local_app_data["tls"] == expected

    def test_provider_publish_updates_all_relations(self, provider_network):
        """Calling publish() with no argument writes host, port and tls to every relation."""
        context = ops.testing.Context(CallableTlsProviderCharm, meta=ProviderCharm.META, config=ProviderCharm.CONFIG)
        relation_a = ops.testing.Relation(RELATION_NAME)
        relation_b = ops.testing.Relation(RELATION_NAME)
        state = ops.testing.State(
            leader=True,
            config={"services": "frontend", "external-hostname": EXTERNAL_HOSTNAME},
            relations=[relation_a, relation_b],
            networks={provider_network},
        )

        # update_status isn't observed by the library, so only the direct
        # publish() call writes anything.
        with context(context.on.update_status(), state) as manager:
            manager.charm.tls_enabled = True
            manager.charm.host_info.publish()
            state_out = manager.run()

        for rel in state_out.get_relations(RELATION_NAME):
            assert rel.local_app_data == {"host": EXTERNAL_HOSTNAME, "port": str(PROVIDER_PORT), "tls": "true"}

    def test_provider_publish_updates_only_the_given_relation(self, provider_context):
        """Calling publish(relation) writes only to that relation."""
        relation_a = ops.testing.Relation(RELATION_NAME)
        relation_b = ops.testing.Relation(RELATION_NAME)
        state = ops.testing.State(
            leader=True,
            config={"services": "frontend", "external-hostname": EXTERNAL_HOSTNAME},
            relations=[relation_a, relation_b],
        )

        with provider_context(provider_context.on.update_status(), state) as manager:
            charm = manager.charm
            charm.host_info.publish(charm.model.get_relation(RELATION_NAME, relation_a.id))
            state_out = manager.run()

        assert state_out.get_relation(relation_a.id).local_app_data["tls"] == "false"
        assert state_out.get_relation(relation_b.id).local_app_data == {}

    @pytest.mark.parametrize(
        "leader, services",
        [(False, "frontend"), (True, "history,matching")],
        ids=["not-leader", "frontend-not-in-services"],
    )
    def test_provider_publish_noop(self, provider_context, provider_relation, leader, services):
        """publish() writes nothing when the unit isn't the leader or doesn't run the frontend."""
        state = ops.testing.State(
            leader=leader,
            config={"services": services, "external-hostname": EXTERNAL_HOSTNAME},
            relations=[provider_relation],
        )

        with provider_context(provider_context.on.update_status(), state) as manager:
            manager.charm.host_info.publish()
            state_out = manager.run()

        assert state_out.get_relations(RELATION_NAME)[0].local_app_data == {}


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
        """Requirer emits temporal_host_info_unavailable when relation is removed."""
        state = ops.testing.State(
            leader=True,
            relations=[requirer_relation_with_data],
        )

        with requirer_context(requirer_context.on.relation_broken(requirer_relation_with_data), state) as manager:
            charm = manager.charm
            manager.run()

        assert len(charm.received_host_info_unavailable) == 1

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

    @pytest.mark.parametrize(
        "published, expected",
        [("true", True), ("True", True), ("false", False), (None, False)],
        ids=["true", "true-mixed-case", "false", "absent"],
    )
    def test_requirer_tls_property(self, requirer_context, published, expected):
        """Requirer tls property reflects the published value; absent means False.

        An absent field is what a provider older than LIBPATCH 2 publishes, and
        those never served the frontend over TLS.
        """
        remote_app_data = {"host": EXTERNAL_HOSTNAME, "port": str(PROVIDER_PORT)}
        if published is not None:
            remote_app_data["tls"] = published
        state = ops.testing.State(
            leader=True,
            relations=[ops.testing.Relation(RELATION_NAME, remote_app_data=remote_app_data)],
        )

        with requirer_context(requirer_context.on.config_changed(), state) as manager:
            charm = manager.charm
            manager.run()

        assert charm.host_info.tls is expected

    def test_requirer_tls_property_false_when_no_relation(self, requirer_context):
        """Requirer tls property is False when no relation is present."""
        state = ops.testing.State(leader=True, relations=[])

        with requirer_context(requirer_context.on.config_changed(), state) as manager:
            charm = manager.charm
            manager.run()

        assert charm.host_info.tls is False

    @pytest.mark.parametrize(
        "published, expected",
        [("true", True), ("false", False), (None, False)],
        ids=["true", "false", "absent"],
    )
    def test_requirer_changed_event_carries_tls(self, requirer_context, published, expected):
        """temporal_host_info_changed carries the published tls value; absent means False."""
        remote_app_data = {"host": EXTERNAL_HOSTNAME, "port": str(PROVIDER_PORT)}
        if published is not None:
            remote_app_data["tls"] = published
        relation = ops.testing.Relation(RELATION_NAME, remote_app_data=remote_app_data)
        state = ops.testing.State(leader=True, relations=[relation])

        with requirer_context(requirer_context.on.relation_changed(relation), state) as manager:
            charm = manager.charm
            manager.run()

        assert len(charm.received_host_info_changed) == 1
        assert charm.received_host_info_changed[0].tls is expected

    @pytest.mark.parametrize(
        "snapshot, expected",
        [
            ({"host": EXTERNAL_HOSTNAME, "port": PROVIDER_PORT, "tls": True}, True),
            # Deferred by a charm running a library older than LIBPATCH 2.
            ({"host": EXTERNAL_HOSTNAME, "port": PROVIDER_PORT}, False),
        ],
        ids=["with-tls", "pre-libpatch-2"],
    )
    def test_changed_event_restores_tls_from_snapshot(self, snapshot, expected):
        """A deferred changed event keeps tls across snapshot/restore; no key means False."""
        event = TemporalHostInfoChangedEvent(ops.Handle(None, "test", "1"), host="", port=0)

        event.restore(snapshot)

        assert event.host == EXTERNAL_HOSTNAME
        assert event.port == PROVIDER_PORT
        assert event.tls is expected
        assert event.snapshot()["tls"] is expected
