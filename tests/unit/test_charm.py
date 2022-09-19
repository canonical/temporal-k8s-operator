# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
#
# Learn more about testing at: https://juju.is/docs/sdk/testing

from unittest import TestCase

from ops.model import ActiveStatus, BlockedStatus
from ops.testing import Harness

from charm import TemporalK8SCharm


class TestCharm(TestCase):

    maxDiff = None

    def setUp(self):
        self.harness = Harness(TemporalK8SCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()
        self.harness.set_can_connect("temporal", True)

    def test_temporal_pebble_ready(self):
        """The pebble plan is correctly generated."""
        harness = self.harness

        # The initial Pebble plan is empty.
        initial_plan = harness.get_container_pebble_plan("temporal")
        self.assertEqual(initial_plan.to_yaml(), "{}\n")

        # The plan is generated after pebble is ready.
        container = harness.model.unit.get_container("temporal")
        harness.charm.on.temporal_pebble_ready.emit(container)
        want_plan = {
            "services": {
                "temporal": {
                    "summary": "temporal server",
                    "command": "temporal-server --env charm start "
                    "--service=frontend --service=history --service=matching --service=worker",
                    "startup": "enabled",
                    "override": "replace",
                    "environment": {"LOG_LEVEL": "info"},
                }
            },
        }
        got_plan = harness.get_container_pebble_plan("temporal").to_dict()
        self.assertEqual(got_plan, want_plan)

        # The service was started.
        service = harness.model.unit.get_container("temporal").get_service("temporal")
        self.assertTrue(service.is_running())

        # The ActiveStatus is set with no message.
        self.assertEqual(harness.model.unit.status, ActiveStatus())

    def test_config_changed(self):
        """The pebble plan changes according to config changes."""
        harness = self.harness

        # Generate the ready plan.
        container = harness.model.unit.get_container("temporal")
        harness.charm.on.temporal_pebble_ready.emit(container)

        # Update the config.
        self.harness.update_config({"log-level": "debug", "services": "worker"})

        # The new plan reflects the change.
        want_plan = {
            "services": {
                "temporal": {
                    "summary": "temporal server",
                    "command": "temporal-server --env charm start --service=worker",
                    "startup": "enabled",
                    "override": "replace",
                    "environment": {"LOG_LEVEL": "debug"},
                }
            },
        }
        got_plan = harness.get_container_pebble_plan("temporal").to_dict()
        self.assertEqual(got_plan, want_plan)

        # The ActiveStatus is set with no message.
        self.assertEqual(harness.model.unit.status, ActiveStatus())

    def test_invalid_config_value(self):
        """The charm blocks if an invalid config value is provided."""
        harness = self.harness

        # Generate the ready plan.
        container = harness.model.unit.get_container("temporal")
        harness.charm.on.temporal_pebble_ready.emit(container)

        # Update the config with an invalid value.
        self.harness.update_config({"services": "worker,bad-wolf"})

        # The change is not applied to the plan.
        want_command = (
            "temporal-server --env charm start --service=frontend --service=history --service=matching --service=worker"
        )
        got_command = harness.get_container_pebble_plan("temporal").to_dict()["services"]["temporal"]["command"]
        self.assertEqual(got_command, want_command)

        # The BlockStatus is set with a message.
        self.assertEqual(
            harness.model.unit.status, BlockedStatus("error in config: services: invalid service 'bad-wolf'")
        )
