# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Define the Temporal server openfga relation."""

import asyncio
import json
import logging
from enum import Enum

import requests
from charms.openfga_k8s.v0.openfga import OpenFGAStoreCreateEvent
from openfga_sdk import TupleKey
from openfga_sdk.client import ClientConfiguration, OpenFgaClient
from openfga_sdk.client.models.check_request import ClientCheckRequest
from openfga_sdk.client.models.list_objects_request import ClientListObjectsRequest
from openfga_sdk.client.models.tuple import ClientTuple
from openfga_sdk.client.models.write_request import ClientWriteRequest
from openfga_sdk.credentials import CredentialConfiguration, Credentials
from openfga_sdk.exceptions import ApiException
from openfga_sdk.models.check_response import CheckResponse
from openfga_sdk.models.read_response import ReadResponse
from ops import framework
from requests.exceptions import RequestException

from literals import ALLOWED_OFGA_ROLES
from log import log_event_handler

logger = logging.getLogger(__name__)


class OFGAOperationType(Enum):
    """Enum of operation types in the OpenFGA store.

    Attributes:
        WRITE: Represents a write operation.
        READ: Represents a read operation.
        LIST: Represents a list operation.
        CHECK: Represents a check operation.
    """

    WRITE = "write"
    READ = "read"
    LIST = "list"
    CHECK = "check"


class AuthRuleActionType(Enum):
    """Enum of operation types in the add/remove actions.

    Attributes:
        CREATE: Represents a create action for authorization rules.
        DELETE: Represents a delete action for authorization rules.
    """

    CREATE = "create"
    DELETE = "delete"


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

        charm.framework.observe(
            charm.on.add_auth_rule_action,
            self._on_add_auth_rule_action,
        )

        charm.framework.observe(
            charm.on.remove_auth_rule_action,
            self._on_remove_auth_rule_action,
        )

        charm.framework.observe(
            charm.on.list_auth_rule_action,
            self._on_list_auth_rule_action,
        )

        charm.framework.observe(
            charm.on.check_auth_rule_action,
            self._on_check_auth_rule_action,
        )

        charm.framework.observe(charm.on.openfga_relation_broken, self._on_openfga_relation_broken)

    @log_event_handler(logger)
    def _on_openfga_store_created(self, event: OpenFGAStoreCreateEvent):
        """Handle OpenFGA relation created event.

        Args:
            event: The event triggered when the relation is created.
        """
        if not self.charm.unit.is_leader():
            return

        if not event.store_id:
            logger.info(f"{event.relation.name} revoked, no store id")
            return

        if event.token_secret_id:
            secret = self.charm.model.get_secret(id=event.token_secret_id)
            secret_content = secret.get_content()
            token = secret_content["token"]
        if event.token:
            token = event.token

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
        if not _check_openfga_relation(self.charm._state, event):
            return

        model = event.params["model"]
        if not model:
            event.set_results({"error": "authorization model not specified"})
            return

        model_json = _parse_model_json(model, event)
        if model_json is None:
            event.set_results({"error": "failed to parse model json"})
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

    @log_event_handler(logger)
    def _on_list_auth_rule_action(self, event):
        """Handle OpenFGA list auth rule action.

        Args:
            event: The event triggered when the action is performed.
        """
        if not _check_openfga_relation(self.charm._state, event):
            return

        valid_combinations = [{"user"}, {"group"}, {"namespace"}]
        valid = _validate_event_params(event, valid_combinations)
        if not valid:
            return

        user = event.params.get("user")
        group = event.params.get("group")
        openfga_data = self.charm._state.openfga

        if user:
            asyncio.run(_list_user_auth_rules(event, openfga_data))
        elif group:
            asyncio.run(_list_group_auth_rules(event, openfga_data))
        else:
            asyncio.run(_list_namespace_auth_rules(event, openfga_data))

    @log_event_handler(logger)
    def _on_check_auth_rule_action(self, event):
        """Handle OpenFGA check auth rule action.

        Args:
            event: The event triggered when the action is performed.
        """
        if not _check_openfga_relation(self.charm._state, event):
            return

        valid_combinations = [{"user", "group"}, {"user", "namespace", "role"}, {"group", "namespace", "role"}]
        valid = _validate_event_params(event, valid_combinations)
        if not valid:
            return

        user = event.params.get("user")
        group = event.params.get("group")
        namespace = event.params.get("namespace")
        role = event.params.get("role")
        openfga_data = self.charm._state.openfga

        if user and group:
            body = ClientCheckRequest(
                user=f"user:{user}",
                relation="member",
                object=f"group:{group}",
            )
        elif user and namespace:
            body = ClientCheckRequest(
                user=f"user:{user}",
                relation=role,
                object=f"namespace:{namespace}",
            )
        else:
            body = ClientCheckRequest(
                user=f"group:{group}#member",
                relation=role,
                object=f"namespace:{namespace}",
            )

        try:
            response: CheckResponse = asyncio.run(
                _perform_ofga_api_call(
                    event=event, openfga_data=openfga_data, body=body, op_type=OFGAOperationType.CHECK
                )
            )
            event.set_results({"result": "command succeeded", "output": response.allowed})
            return
        except ApiException:
            event.set_results({"error": "failed to perform ofga operation"})

    @log_event_handler(logger)
    def _on_add_auth_rule_action(self, event):
        """Handle OpenFGA add auth rule action.

        Args:
            event: The event triggered when the action is performed.
        """
        if not _check_openfga_relation(self.charm._state, event):
            return

        asyncio.run(self._perform_add_or_remove_auth_rule(event, AuthRuleActionType.CREATE))

    @log_event_handler(logger)
    def _on_remove_auth_rule_action(self, event):
        """Handle OpenFGA remove auth rule action.

        Args:
            event: The event triggered when the action is performed.
        """
        if not _check_openfga_relation(self.charm._state, event):
            return

        asyncio.run(self._perform_add_or_remove_auth_rule(event, AuthRuleActionType.DELETE))

    async def _perform_add_or_remove_auth_rule(self, event, action_type: AuthRuleActionType):
        """Handle OpenFGA add auth/remove auth rule action.

        Args:
            event: The event triggered when the action is performed.
            action_type: one of AuthRuleActionType.CREATE or AuthRuleActionType.DELETE
        """
        valid_combinations = [{"user", "group"}, {"group", "namespace", "role"}]
        valid = _validate_event_params(event, valid_combinations)
        if not valid:
            return

        user = event.params.get("user")
        group = event.params.get("group")
        namespace = event.params.get("namespace")
        role = event.params.get("role")
        openfga_data = self.charm._state.openfga

        if user:
            op_tuple = [
                ClientTuple(
                    user=f"user:{user}",
                    relation="member",
                    object=f"group:{group}",
                ),
            ]

            if action_type == AuthRuleActionType.DELETE:
                body = ClientWriteRequest(deletes=op_tuple)
            else:
                body = ClientWriteRequest(writes=op_tuple)

            try:
                await _perform_ofga_api_call(
                    event=event, openfga_data=openfga_data, body=body, op_type=OFGAOperationType.WRITE
                )
                logger.info(f"openfga: operation type {action_type!r} for user {user!r} on group {group!r} successful")
                event.set_results(
                    {
                        "result": "command succeeded",
                        "output": f"operation type {action_type!r} for user {user!r} on group {group!r} successful",
                    }
                )
                return
            except ApiException:
                event.set_results({"error": "failed to perform ofga operation"})
        else:
            if role not in ALLOWED_OFGA_ROLES:
                event.set_results({"error": f"provided role {role!r} not in allowed roles: {ALLOWED_OFGA_ROLES!r}"})
                return

            op_tuple = [
                ClientTuple(
                    user=f"group:{group}#member",
                    relation=role,
                    object=f"namespace:{namespace}",
                ),
            ]

            if action_type == AuthRuleActionType.DELETE:
                body = ClientWriteRequest(deletes=op_tuple)
            else:
                body = ClientWriteRequest(writes=op_tuple)

            try:
                await _perform_ofga_api_call(
                    event=event, openfga_data=openfga_data, body=body, op_type=OFGAOperationType.WRITE
                )
                logger.info(
                    f"openfga: operation type {action_type!r} for group {group!r} and role {role!r} on namespace {namespace!r} successful"
                )
                event.set_results(
                    {
                        "result": "command succeeded",
                        "output": f"operation type {action_type!r} for group {group!r} and role {role!r} on namespace {namespace!r} successful",
                    }
                )
                return
            except ApiException:
                event.set_results({"error": "failed to perform ofga operation"})


def _validate_event_params(event, valid_combinations):
    """Validate event parameters against a list of valid parameter combinations.

    Args:
        event: The event triggered when the action is performed.
        valid_combinations: A list of valid parameter combinations, where
            each combination is represented as a set of parameter keys.

    Returns:
        bool: True if the provided parameters match any valid combination; False otherwise.
    """
    valid = False
    for valid_combination in valid_combinations:
        if event.params.keys() == valid_combination:
            valid = True

    if not valid:
        valid_combination_strings = []
        for i, combination in enumerate(valid_combinations):
            valid_combination_strings.append(f"{i+1}. '{', '.join(combination)}'")

        valid_combinations_message = "\n".join(valid_combination_strings)
        event.set_results(
            {
                "error": f"parameter combination not supported. parameters for this operation must either be:\n{valid_combinations_message}"
            }
        )

    return valid


def _get_ofga_client(openfga_data):
    """Create and configure an OpenFGA client.

    Args:
        openfga_data: Object containing OpenFGA store data.

    Returns:
        OpenFgaClient: An initialized OpenFgaClient instance configured to interact
        with the OpenFGA store.
    """
    configuration = ClientConfiguration(
        api_scheme=openfga_data["scheme"],
        api_host=f"{openfga_data['address']}:{openfga_data['port']}",
        store_id=openfga_data["store_id"],
        authorization_model_id=openfga_data["auth_model_id"],
        credentials=Credentials(
            method="api_token",
            configuration=CredentialConfiguration(
                api_token=openfga_data["token"],
            ),
        ),
    )

    return OpenFgaClient(configuration)


async def _perform_ofga_api_call(event, openfga_data, body, op_type):
    """Perform an OpenFGA API call based on the specified operation type.

    Args:
        event: The event triggered when the action is performed.
        openfga_data: Object containing OpenFGA store data.
        body: The request body for the OpenFGA API call, specific to the operation type.
        op_type: OFGAOperationType operation.

    Returns:
        Response: The response from the OpenFGA API call, which varies based on the
        operation type.

    Raises:
        e: If an error occurs during the OpenFGA API call.
    """
    ofga_client = _get_ofga_client(openfga_data)

    try:
        if op_type == OFGAOperationType.CHECK:
            response = await ofga_client.check(body)
        elif op_type == OFGAOperationType.LIST:
            response = await ofga_client.list_objects(body)
            response = response.objects
        elif op_type == OFGAOperationType.WRITE:
            await ofga_client.write(body)
            response = None
        elif op_type == OFGAOperationType.READ:
            continuation_token = ""  # nosec B105
            results = []
            while True:
                read_response = await ofga_client.read(body)
                results.extend(read_response.tuples)
                continuation_token = read_response.continuation_token
                if continuation_token == "":  # nosec B105
                    break
            response = results

        await ofga_client.close()
        return response

    except ApiException as e:
        raise e


async def _list_user_auth_rules(event, openfga_data):
    """List a user's authorization rules from the OpenFGA store.

    Args:
        event: The event triggered when the action is performed.
        openfga_data: Object containing OpenFGA store data.
    """
    results = {key: [] for key in ALLOWED_OFGA_ROLES}
    body = ClientListObjectsRequest(
        user=f"user:{event.params.get('user')}",
        relation="member",
        type="group",
    )
    try:
        response: ClientListObjectsRequest = await _perform_ofga_api_call(
            event=event, openfga_data=openfga_data, body=body, op_type=OFGAOperationType.LIST
        )
        results["member"] = response

        for role in ALLOWED_OFGA_ROLES:
            body = ClientListObjectsRequest(
                user=f"user:{event.params.get('user')}",
                relation=role,
                type="namespace",
            )
            response: ClientListObjectsRequest = await _perform_ofga_api_call(
                event=event, openfga_data=openfga_data, body=body, op_type=OFGAOperationType.LIST
            )
            results[role] = response

        event.set_results({"result": "command succeeded", "output": results})
    except ApiException:
        event.set_results({"error": "failed to perform ofga operation"})


async def _list_group_auth_rules(event, openfga_data):
    """List a group's authorization rules from the OpenFGA store.

    Args:
        event: The event triggered when the action is performed.
        openfga_data: Object containing OpenFGA store data.
    """
    try:
        results = {key: [] for key in ALLOWED_OFGA_ROLES}
        for role in ALLOWED_OFGA_ROLES:
            body = ClientListObjectsRequest(
                user=f"group:{event.params.get('group')}#member",
                relation=role,
                type="namespace",
            )
            response: ClientListObjectsRequest = await _perform_ofga_api_call(
                event=event, openfga_data=openfga_data, body=body, op_type=OFGAOperationType.LIST
            )
            results[role] = response

        event.set_results({"result": "command succeeded", "output": results})
    except ApiException:
        event.set_results({"error": "failed to perform ofga operation"})


async def _list_namespace_auth_rules(event, openfga_data):
    """List a namespace's authorization rules from the OpenFGA store.

    Args:
        event: The event triggered when the action is performed.
        openfga_data: object containing OpenFGA store data.
    """
    try:
        results = {key: [] for key in ALLOWED_OFGA_ROLES}
        body = TupleKey(
            object=f"namespace:{event.params.get('namespace')}",
        )

        response: ReadResponse = await _perform_ofga_api_call(
            event=event, openfga_data=openfga_data, body=body, op_type=OFGAOperationType.READ
        )

        for result in response:
            # extract format "group:<name>#member" into "group:<name>"
            group = result.key.user.split("#")[0]
            results[result.key.relation].append(group)

        event.set_results({"result": "command succeeded", "output": results})
    except ApiException:
        event.set_results({"error": "failed to perform ofga operation"})


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
