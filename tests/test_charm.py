# Copyright 2022 Canonical.
# See LICENSE file for licensing details.
#
# Learn more about testing at: https://juju.is/docs/sdk/testing

from unittest import TestCase

from ops.model import ActiveStatus
from ops.testing import Harness

from charm import TemporalK8SCharm


class TestCharm(TestCase):

    maxDiff = None

    def setUp(self):
        self.harness = Harness(TemporalK8SCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()

    def test_temporal_pebble_ready(self):
        """The pebble plan is correctly generated."""
        harness = self.harness
        harness.set_can_connect("temporal", True)

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
        harness.set_can_connect("temporal", True)

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
