# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Archival implementation."""

import functools
import hashlib
import json
import logging

import boto3
import botocore
from botocore.exceptions import ClientError
from charms.data_platform_libs.v0.s3 import (
    CredentialsChangedEvent,
    CredentialsGoneEvent,
)

logger = logging.getLogger(__name__)


def retrieve_s3_parameters(s3_client):
    """Retrieve S3 parameters from the S3 integrator relation.

    Args:
        s3_client: The S3 requirer library object.

    Returns:
        s3 parameters (dict) and any missing parameters (list) from the relation.
    """
    s3_parameters = s3_client.get_s3_connection_info()
    required_parameters = [
        "bucket",
        "access-key",
        "secret-key",
    ]
    missing_required_parameters = [param for param in required_parameters if param not in s3_parameters]
    if missing_required_parameters:
        logger.warning(f"Missing required S3 parameters in relation with S3 integrator: {missing_required_parameters}")
        return {}, missing_required_parameters

    # Add some sensible defaults (as expected by the code) for missing optional parameters
    s3_parameters.setdefault("endpoint", "https://s3.amazonaws.com")
    s3_parameters.setdefault("region", "")
    s3_parameters.setdefault("path", "")
    s3_parameters.setdefault("s3-uri-style", "host")

    # Strip whitespaces from all parameters.
    for key, value in s3_parameters.items():
        if isinstance(value, str):
            s3_parameters[key] = value.strip()

    # Clean up extra slash symbols to avoid issues on 3rd-party storages
    # like Ceph Object Gateway (radosgw).
    s3_parameters["endpoint"] = s3_parameters["endpoint"].rstrip("/")
    s3_parameters[
        "path"
    ] = f'/{s3_parameters["path"].strip("/")}'  # The slash in the beginning is required by pgBackRest.
    s3_parameters["bucket"] = s3_parameters["bucket"].strip("/")

    return s3_parameters, []


def construct_endpoint(s3_parameters):
    """Construct the S3 service endpoint using the region.

    This is needed when the provided endpoint is from AWS, and it doesn't contain the region.

    Args:
        s3_parameters: s3 parameters fetched from the s3 integrator relation.

    Returns:
        S3 service endpoint.
    """
    # Use the provided endpoint if a region is not needed.
    endpoint = s3_parameters["endpoint"]

    # Load endpoints data.
    loader = botocore.loaders.create_loader()
    data = loader.load_data("endpoints")

    # Construct the endpoint using the region.
    resolver = botocore.regions.EndpointResolver(data)
    endpoint_data = resolver.construct_endpoint("s3", s3_parameters["region"])

    # Use the built endpoint if it is an AWS endpoint.
    if endpoint_data and endpoint.endswith(endpoint_data["dnsSuffix"]):
        endpoint = f'{endpoint.split("://")[0]}://{endpoint_data["hostname"]}'

    return endpoint


def create_bucket_if_not_exists(s3_parameters, endpoint):
    """Create the S3 bucket if it does not exist.

    Args:
        s3_parameters: s3 parameters fetched from the s3 integrator relation.
        endpoint: S3 service endpoint.

    Raises:
        e (ValueError): if a session could not be created.
        error (ClientError): if the bucket could not be created.
    """
    bucket_name = s3_parameters["bucket"]
    region = s3_parameters.get("region")
    session = boto3.session.Session(
        aws_access_key_id=s3_parameters["access-key"],
        aws_secret_access_key=s3_parameters["secret-key"],
        region_name=s3_parameters["region"],
    )

    try:
        s3 = session.resource("s3", endpoint_url=endpoint)
    except ValueError as e:
        logger.exception("Failed to create a session '%s' in region=%s.", bucket_name, region)
        raise e
    bucket = s3.Bucket(bucket_name)
    try:
        bucket.meta.client.head_bucket(Bucket=bucket_name)
        logger.info("Bucket %s exists.", bucket_name)
        exists = True
    except ClientError:
        logger.warning("Bucket %s doesn't exist or you don't have access to it.", bucket_name)
        exists = False

    if not exists:
        try:
            bucket.create(CreateBucketConfiguration={"LocationConstraint": region})

            bucket.wait_until_exists()
            logger.info("Created bucket '%s' in region=%s", bucket_name, region)
        except ClientError as error:
            logger.exception("Couldn't create bucket named '%s' in region=%s.", bucket_name, region)
            raise error


class S3Archival:
    """Read S3 relation data and preserve bucket state during rolling upgrades.

    Attributes:
        charm: The charm that owns the S3 requirer and peer relation.
        connection: S3 parameters and normalized state derived from the relation.
        bucket_creator: Function that ensures the S3 bucket exists.
    """

    def __init__(self, charm, bucket_creator):
        """Construct the helper.

        Args:
            charm: The charm that owns the S3 requirer and peer relation.
            bucket_creator: Function that ensures the S3 bucket exists.
        """
        self.charm = charm
        self.bucket_creator = bucket_creator

    @functools.cached_property
    def connection(self):
        """Return S3 relation parameters and the normalized state derived from them."""
        charm = self.charm
        if not charm.model.get_relation("s3-parameters"):
            return None, None

        s3_parameters, missing_parameters = retrieve_s3_parameters(charm.s3_client)
        if missing_parameters:
            return None, None

        state = {
            "bucket": s3_parameters.get("bucket"),
            "endpoint": construct_endpoint(s3_parameters),
            "region": s3_parameters.get("region"),
            "aws_access_key_id": s3_parameters.get("access-key"),
            "aws_secret_access_key": s3_parameters.get("secret-key"),
            "uri_style": s3_parameters.get("s3-uri-style"),
        }
        return s3_parameters, state

    @staticmethod
    def fingerprint(s3_state) -> str:
        """Return a fingerprint of the S3 state.

        Args:
            s3_state: The normalized S3 connection data.

        Returns:
            A deterministic fingerprint for the connection data.
        """
        return hashlib.sha256(json.dumps(s3_state, sort_keys=True).encode()).hexdigest()

    def state(self):
        """Return usable S3 state and its recorded bucket outcome, if available.

        Returns:
            The S3 state dict, or None if the relation is unusable or the bucket outcome is not
            recorded.
        """
        charm = self.charm
        _, s3_state = self.connection
        if s3_state is None:
            return None

        record = charm._peer_get("s3_bucket")
        if isinstance(record, dict) and record.get("fingerprint") == self.fingerprint(s3_state):
            return {**s3_state, "bucket_created": bool(record.get("bucket_created"))}

        legacy = charm._peer_get("s3")
        if isinstance(legacy, dict) and "bucket_created" in legacy:
            credentials = {key: value for key, value in legacy.items() if key != "bucket_created"}
            if credentials == s3_state:
                return {**s3_state, "bucket_created": bool(legacy["bucket_created"])}
        return None

    def reconcile_legacy_peer_state(self, event):
        """Keep the legacy S3 peer data up to date for rolling upgrades.

        Args:
            event: The event being reconciled.
        """
        charm = self.charm
        stored = charm._peer_get("s3")
        state = self.state()
        if state is not None:
            if state != stored:
                charm._peer_set("s3", state)
        elif stored is not None and (
            isinstance(event, CredentialsGoneEvent) or not charm.model.get_relation("s3-parameters")
        ):
            charm._peer_set("s3", None)

    def reconcile_bucket(self, event):
        """Create the bucket for new credentials and persist permanent outcomes.

        Args:
            event: The event being reconciled.

        Returns:
            True when a transient error occurred.
        """
        charm = self.charm
        s3_parameters, s3_state = self.connection
        if s3_state is None:
            charm._peer_delete("s3_bucket")
            return False

        fingerprint = self.fingerprint(s3_state)
        record = charm._peer_get("s3_bucket")
        if (
            isinstance(record, dict)
            and record.get("fingerprint") == fingerprint
            and not isinstance(event, CredentialsChangedEvent)
        ):
            return False

        try:
            self.bucket_creator(s3_parameters, s3_state["endpoint"])
        except (ClientError, ValueError):
            bucket_created = False
        except Exception:  # pylint: disable=broad-exception-caught
            logger.exception("failed to create the S3 bucket %s", s3_parameters.get("bucket"))
            return True
        else:
            bucket_created = True

        if not bucket_created:
            logger.warning("S3 bucket %s could not be created or checked", s3_parameters.get("bucket"))
        charm._peer_set("s3_bucket", {"fingerprint": fingerprint, "bucket_created": bucket_created})
        return False
