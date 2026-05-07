# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Define the Temporal server ui relation — stateless utility."""

import logging

logger = logging.getLogger(__name__)


def provide_server_status(charm):
    """Provide server status to the UI charm.

    Args:
        charm: The charm instance.
    """
    ui_relations = charm.model.relations["ui"]
    if not ui_relations:
        return
    for relation in ui_relations:
        relation.data[charm.app].update({"server_status": "ready"})
