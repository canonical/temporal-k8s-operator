#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd Ltd.
# See LICENSE file for licensing details.

from temporalio import activity


@activity.defn
async def say_hello(name: str) -> str:
    return f"Hello, {name}!"
