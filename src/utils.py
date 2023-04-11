# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""General purpose helper functions for manaing common charm functions."""

import logging

from ops.model import Container

logger = logging.getLogger(__name__)


def push_to_file(container: Container, content: str, path: str) -> None:
    """Wrapper for writing a file and contents to a container.
    Args:
        container: container to push the files into
        content: the text content to write to a file path
        path: the full path of the desired file
    """
    container.push(path, content, make_dirs=True)
