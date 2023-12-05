# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
#
# Learn more at: https://juju.is/docs/sdk

"""Literals used by the Temporal K8s charm."""

from enum import Enum

VALID_LOG_LEVELS = ["info", "debug", "warning", "error", "critical"]
LOG_FILE = "/var/log/temporal"
DB_NAME = "temporal-k8s_db"
VISIBILITY_DB_NAME = "temporal-k8s_visibility"
ALLOWED_OFGA_ROLES = ["admin", "writer", "reader"]

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
    "internal-frontend": {
        "grpc": 7236,
        "http": 6936,
    },
}

PROMETHEUS_PORT = 9090


class ValidServiceTypes(Enum):
    """Enum of valid service types in Temporal.

    Attributes:
        FRONTEND: Represents the frontend service.
        HISTORY: Represents the history service.
        MATCHING: Represents the matching service.
        WORKER: Represents the worker service.
    """

    FRONTEND = "frontend"
    HISTORY = "history"
    MATCHING = "matching"
    WORKER = "worker"
