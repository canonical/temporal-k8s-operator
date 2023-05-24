# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
#
# Learn more at: https://juju.is/docs/sdk

"""Literals used by the Temporal K8s charm."""

VALID_LOG_LEVELS = ["info", "debug", "warning", "error", "critical"]
LOG_FILE = "/var/log/temporal"
DB_NAME = "temporal-k8s_db"
VISIBILITY_DB_NAME = "temporal-k8s_visibility"

SERVICE_PORTS = {
    "frontend": {
        "grpc": 7233,
        "http": 6933,
    },
    "matching": {
        "grpc": 7235,
        "http": 6935,
    },
    "history": {
        "grpc": 7234,
        "http": 6934,
    },
    "worker": {
        "grpc": 7239,
        "http": 6939,
    },
}

PROMETHEUS_PORT = 9090
