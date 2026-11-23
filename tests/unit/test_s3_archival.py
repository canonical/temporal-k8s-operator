# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit tests for S3 bucket error classification and creation."""

from unittest.mock import patch

import pytest
from botocore.exceptions import ClientError

from relations.s3_archival import _is_retryable_s3_error, create_bucket_if_not_exists

RETRYABLE_CODES = [
    "SlowDown",
    "Throttling",
    "ThrottlingException",
    "RequestLimitExceeded",
    "TooManyRequestsException",
    "RequestTimeout",
    "RequestTimeoutException",
    "InternalError",
    "InternalFailure",
    "ServiceUnavailable",
]


@pytest.mark.parametrize("code", RETRYABLE_CODES)
def test_retryable_error_code_without_http_metadata(code):
    """Recognize transient service codes even without HTTP response metadata."""
    error = ClientError({"Error": {"Code": code}}, "HeadBucket")

    assert _is_retryable_s3_error(error) is True


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_retryable_http_status_with_unknown_error_code(status):
    """Recognize transient HTTP statuses independently of the service code."""
    error = ClientError(
        {"Error": {"Code": "UnknownError"}, "ResponseMetadata": {"HTTPStatusCode": status}},
        "HeadBucket",
    )

    assert _is_retryable_s3_error(error) is True


@pytest.mark.parametrize(
    "response",
    [
        {},
        {"Error": {"Code": "UnknownError"}},
        {"Error": {"Code": "InvalidBucketName"}, "ResponseMetadata": {"HTTPStatusCode": 400}},
        {"Error": {"Code": "AccessDenied"}, "ResponseMetadata": {"HTTPStatusCode": 403}},
        {"Error": {"Code": "NoSuchBucket"}, "ResponseMetadata": {"HTTPStatusCode": 404}},
    ],
)
def test_permanent_error_is_not_retryable(response):
    """Do not retry missing or permanent error codes and HTTP statuses."""
    assert _is_retryable_s3_error(ClientError(response, "HeadBucket")) is False


@pytest.fixture
def s3_parameters():
    """Return bucket parameters without contacting S3."""
    return {"bucket": "test-bucket", "region": "test-region", "access-key": "access", "secret-key": "secret"}


@pytest.fixture
def bucket(s3_parameters):
    """Mock the boto3 session and return its bucket."""
    with patch("relations.s3_archival.boto3.session.Session") as session:
        yield session.return_value.resource.return_value.Bucket.return_value
        session.assert_called_once_with(
            aws_access_key_id=s3_parameters["access-key"],
            aws_secret_access_key=s3_parameters["secret-key"],
            region_name=s3_parameters["region"],
        )
        session.return_value.resource.assert_called_once_with("s3", endpoint_url="https://s3.example.com")
        session.return_value.resource.return_value.Bucket.assert_called_once_with("test-bucket")


@pytest.mark.parametrize(
    "response",
    [
        pytest.param({"Error": {"Code": "SlowDown"}}, id="SlowDown"),
        pytest.param(
            {"Error": {"Code": "UnknownError"}, "ResponseMetadata": {"HTTPStatusCode": 503}},
            id="http-503",
        ),
    ],
)
def test_transient_head_error_propagates_without_creating_bucket(bucket, s3_parameters, response):
    """Propagate transient bucket checks without attempting creation."""
    error = ClientError(response, "HeadBucket")
    bucket.meta.client.head_bucket.side_effect = error

    with pytest.raises(ClientError) as raised:
        create_bucket_if_not_exists(s3_parameters, "https://s3.example.com")

    assert raised.value is error
    bucket.meta.client.head_bucket.assert_called_once_with(Bucket="test-bucket")
    bucket.create.assert_not_called()
    bucket.wait_until_exists.assert_not_called()


@pytest.mark.parametrize("code", ["AccessDenied", "NoSuchBucket"])
def test_permanent_head_error_preserves_bucket_creation(bucket, s3_parameters, code):
    """Preserve creation after permanent or not-found bucket check errors."""
    bucket.meta.client.head_bucket.side_effect = ClientError({"Error": {"Code": code}}, "HeadBucket")

    create_bucket_if_not_exists(s3_parameters, "https://s3.example.com")

    bucket.meta.client.head_bucket.assert_called_once_with(Bucket="test-bucket")
    bucket.create.assert_called_once_with(CreateBucketConfiguration={"LocationConstraint": "test-region"})
    bucket.wait_until_exists.assert_called_once_with()


def test_existing_bucket_is_not_created(bucket, s3_parameters):
    """A successful bucket check does not create or wait for the bucket."""
    create_bucket_if_not_exists(s3_parameters, "https://s3.example.com")

    bucket.meta.client.head_bucket.assert_called_once_with(Bucket="test-bucket")
    bucket.create.assert_not_called()
    bucket.wait_until_exists.assert_not_called()


def test_transient_create_error_propagates(bucket, s3_parameters):
    """Propagate a transient creation failure without waiting for the bucket."""
    bucket.meta.client.head_bucket.side_effect = ClientError({"Error": {"Code": "NoSuchBucket"}}, "HeadBucket")
    error = ClientError({"Error": {"Code": "SlowDown"}}, "CreateBucket")
    bucket.create.side_effect = error

    with pytest.raises(ClientError) as raised:
        create_bucket_if_not_exists(s3_parameters, "https://s3.example.com")

    assert raised.value is error
    bucket.create.assert_called_once_with(CreateBucketConfiguration={"LocationConstraint": "test-region"})
    bucket.wait_until_exists.assert_not_called()
