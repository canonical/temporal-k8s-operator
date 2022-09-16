#!/usr/bin/env python3
# Copyright 2022 Canonical.
# See LICENSE file for licensing details.
#
# Learn more at: https://juju.is/docs/sdk

"""Charm definition and helpers."""

import functools
import logging
import os

from jinja2 import Environment, FileSystemLoader
from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, MaintenanceStatus, WaitingStatus

logger = logging.getLogger(__name__)


def log_event_handler(method):
    """Log when a event handler method is executed."""

    @functools.wraps(method)
    def decorated(self, event):
        logger.debug(f"running {method.__name__}")
        try:
            return method(self, event)
        finally:
            logger.debug(f"completed {method.__name__}")

    return decorated


def render(template_name, context):
    """Render the template with the given name using the given context dict."""
    charm_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
    loader = FileSystemLoader(os.path.join(charm_dir, "templates"))
    return Environment(loader=loader).get_template(template_name).render(**context)


class TemporalK8SCharm(CharmBase):
    """Temporal server charm."""

    def __init__(self, *args):
        super().__init__(*args)
        self.name = "temporal"

        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.temporal_pebble_ready, self._on_temporal_pebble_ready)
        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(self.on.restart_action, self._on_restart_action)

    @log_event_handler
    def _on_install(self, event):
        """Install temporal."""
        self.unit.status = MaintenanceStatus("installing temporal")

    @log_event_handler
    def _on_temporal_pebble_ready(self, event):
        """Define and start temporal using the Pebble API."""
        self._update(event)

    @log_event_handler
    def _on_config_changed(self, event):
        """Handle configuration changes."""
        self.unit.status = WaitingStatus("configuring temporal")
        self._update(event)

    @log_event_handler
    def _on_restart_action(self, event):
        """Restart the temporal server, even if there are no changes."""
        container = self.unit.get_container(self.name)

        logging.info("restarting temporal")
        self.unit.status = MaintenanceStatus("restarting temporal")
        container.restart(self.name)
        self.unit.status = ActiveStatus()

    def _update(self, event):
        """Update the Temporal server configuration and replan its execution."""
        container = self.unit.get_container(self.name)
        if not container.can_connect():
            event.defer()
            return

        logging.info("configuring temporal")
        options = {
            "log-level": "LOG_LEVEL",
        }
        context = {config_key: self.config[key] for key, config_key in options.items()}
        config = render("config.jinja", context)
        container.push("/etc/temporal/config/charm.yaml", config, make_dirs=True)

        logging.info("planning temporal execution")
        services = self.config["services"].split(",")
        services_args = " ".join(f"--service={service}" for service in services)
        pebble_layer = {
            "summary": "temporal server layer",
            "services": {
                self.name: {
                    "summary": "temporal server",
                    "command": "temporal-server --env charm start " + services_args,
                    "startup": "enabled",
                    "override": "replace",
                    # Including config values here so that a change in the
                    # config forces replanning to restart the service.
                    "environment": context,
                }
            },
        }
        container.add_layer(self.name, pebble_layer, combine=True)
        container.replan()

        self.unit.status = ActiveStatus()


if __name__ == "__main__":
    main(TemporalK8SCharm)
