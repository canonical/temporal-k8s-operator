# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.


"""Temporal client activity."""

from temporalio import activity


@activity.defn
async def say_hello(name: str) -> str:
    """Temporal activity.

    Args:
        name: used to run the dynamic activity.

    Returns:
        String in the form "Hello, {name}!
    """
    return f"Hello, {name}!"
