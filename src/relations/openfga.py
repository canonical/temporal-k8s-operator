# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Define the Temporal server openfga relation."""

import json
import logging

import requests
from charms.openfga_k8s.v0.openfga import OpenFGAStoreCreateEvent
from ops import framework

from log import log_event_handler

logger = logging.getLogger(__name__)


class OpenFGA(framework.Object):
    """Client for openfga:temporal relations."""

    def __init__(self, charm):
        """Construct.

        Args:
            charm: The charm to attach the hooks to.
        """
        super().__init__(charm, "openfga")
        self.charm = charm
        # Register OpenFGA relation handlers.
        charm.framework.observe(
            charm.openfga.on.openfga_store_created,
            self._on_openfga_store_created,
        )
        charm.framework.observe(
            charm.on.create_authorization_model_action,
            self._on_create_authorization_model_action,
        )
        charm.framework.observe(charm.on.openfga_relation_broken, self._on_openfga_relation_broken)

    @log_event_handler(logger)
    def _on_openfga_store_created(self, event: OpenFGAStoreCreateEvent):
        """Handle OpenFGA relation created event.

        Args:
            event: The event triggered when the relation is created.
        """
        if not event.store_id:
            logger.info(f"{event.relation.name} revoked, no store id")
            return

        token = event.token
        if event.token_secret_id:
            secret = self.charm.model.get_secret(id=event.token_secret_id)
            secret_content = secret.get_content()
            token = secret_content["token"]

        if self.charm.unit.is_leader():
            self.charm._state.openfga = {
                "store_id": event.store_id,
                "token": token,
                "address": event.address,
                "port": event.port,
                "scheme": event.scheme,
                "auth_model_id": None,
            }

        self.charm._update(event)

    @log_event_handler(logger)
    def _on_openfga_relation_broken(self, event) -> None:
        """Handle broken relations with OpenFGA.

        Args:
            event: The event triggered when the relation changed.
        """
        if not self.charm._state.is_ready():
            event.defer()
            return

        if self.charm.unit.is_leader():
            self.charm._state.openfga = None
            self.charm._update(event)

    @log_event_handler(logger)
    def _on_create_authorization_model_action(self, event):
        """Handle OpenFGA relation created event.

        Args:
            event: The event triggered when the relation is created.
        """
        model = event.params["model"]
        if not model:
            event.fail("authorization model not specified")
            return
        try:
            model_json = json.loads(model)
        except json.decoder.JSONDecodeError as error:
            event.fail(f"error occurred: {error}")
            return

        if not self.charm._state.openfga:
            event.fail("missing openfga relation")
            return
        openfga_store_id = self.charm._state.openfga["store_id"]
        openfga_token = self.charm._state.openfga["token"]
        openfga_address = self.charm._state.openfga["address"]
        openfga_port = self.charm._state.openfga["port"]
        openfga_scheme = self.charm._state.openfga["scheme"]
        url = f"{openfga_scheme}://{openfga_address}:{openfga_port}/stores/{openfga_store_id}/authorization-models"
        headers = {"Content-Type": "application/json"}
        if openfga_token:
            headers["Authorization"] = f"Bearer {openfga_token}"

        # do the post request
        logger.info(f"posting to {url}, with headers {headers}")
        try:
            response = requests.post(url, json=model_json, headers=headers, timeout=10)
        except requests.HTTPError as error:
            logger.info(f"error occurred in: {error}")
            event.fail(f"error occurred in: {error}")
            return

        if not response.ok:
            logger.info(f"failed to create authorization model: {response.text}")
            event.fail(
                f"failed to create the authorization model: {response.text}",
            )
            return

        data = response.json()
        authorization_model_id = data.get("authorization_model_id", "")
        if not authorization_model_id:
            logger.info(f"response does not contain authorization model id: {response.text}")
            event.fail(f"response does not contain authorization model id: {response.text}")
            return
        logger.info(f"auth model id is {authorization_model_id}")
        # Replacing the whole openfga dict to include the auth model id.
        self.charm._state.openfga = {
            **self.charm._state.openfga,
            "auth_model_id": authorization_model_id,
        }
        self.charm._update(event)
