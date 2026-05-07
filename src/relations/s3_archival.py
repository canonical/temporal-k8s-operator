# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Archival implementation — stateless utility functions."""

import logging

import boto3
import botocore
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


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
