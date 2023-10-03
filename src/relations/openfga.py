# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Define the Temporal server openfga relation."""

import json
import logging

import requests
from charms.openfga_k8s.v0.openfga import OpenFGAStoreCreateEvent
from ops import framework
from requests.exceptions import RequestException

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
        """Handle OpenFGA create authorization model action.

        Args:
            event: The event triggered when the action is performed.
        """
        model = event.params["model"]
        if not model:
            event.fail("authorization model not specified")
            return

        model_json = _parse_model_json(model, event)
        if model_json is None:
            event.fail("failed to parse model json")
            return

        if not _check_openfga_relation(self.charm._state, event):
            return

        openfga_data = self.charm._state.openfga
        url = f"{openfga_data['scheme']}://{openfga_data['address']}:{openfga_data['port']}/stores/{openfga_data['store_id']}/authorization-models"
        headers = _build_headers(openfga_data)

        response = _post_authorization_model(url, model_json, headers, event)
        if response is None:
            return

        authorization_model_id = _extract_authorization_model_id(response, event)
        if not authorization_model_id:
            return

        # Replacing the whole openfga dict to include the auth model id.
        self.charm._state.openfga = {
            **self.charm._state.openfga,
            "auth_model_id": authorization_model_id,
        }
        self.charm._update(event)


def _parse_model_json(model, event):
    """Parse OpenFGA authorization model.

    Args:
        model: Model provided through the action.
        event: The event triggered when the action is performed.

    Returns:
        Parsed model.
    """
    try:
        return json.loads(model)
    except json.decoder.JSONDecodeError as error:
        error_msg = f"error occurred: {error}"
        event.fail(error_msg)
        logger.info(error_msg)
        return None


def _check_openfga_relation(state, event):
    """Check for presence of OpenFGA relation.

    Args:
        state: Model provided through the action.
        event: The event triggered when the action is performed.

    Returns:
        Whether or not the OpenFGA relation exists.
    """
    if not state.openfga:
        event.fail("missing openfga relation")
        logger.info("missing openfga relation")
        return False
    return True


def _build_headers(openfga_data):
    """Build Authorization header for OpenFGA store requests.

    Args:
        openfga_data: OpenFGA store information.

    Returns:
        Request headers.
    """
    headers = {"Content-Type": "application/json"}
    if openfga_data["token"]:
        headers["Authorization"] = f"Bearer {openfga_data['token']}"
    return headers


def _post_authorization_model(url, model_json, headers, event):
    """Create authorization model in OpenFGA store.

    Args:
        url: OpenFGA store authorization models URL.
        model_json: JSON representation of the provided authorization model.
        headers: Request headers.
        event: The event triggered when the action is performed.

    Returns:
        HTTP Response after creating the OpenFGA authorization model.
    """
    logger.info(f"posting to {url}, with headers {headers}")
    try:
        response = requests.post(url, json=model_json, headers=headers, timeout=10)
        response.raise_for_status()
        return response
    except RequestException as error:
        error_msg = f"error occurred in: {error}"
        event.fail(error_msg)
        logger.info(error_msg)
        return None


def _extract_authorization_model_id(response, event):
    """Extract authorization model ID from response.

    Args:
        response: Response from the creation request.
        event: The event triggered when the action is performed.

    Returns:
        OpenFGA authorization model ID.
    """
    if not response.ok:
        error_msg = f"failed to create authorization model: {response.text}"
        event.fail(error_msg)
        logger.info(error_msg)
        return None

    data = response.json()
    authorization_model_id = data.get("authorization_model_id", "")
    if not authorization_model_id:
        error_msg = f"response does not contain authorization model id: {response.text}"
        event.fail(error_msg)
        logger.info(error_msg)
        return None

    logger.info(f"auth model id is {authorization_model_id}")
    return authorization_model_id
