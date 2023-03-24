#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd Ltd.
# See LICENSE file for licensing details.


"""Temporal client sample workflow."""

from datetime import timedelta

from temporalio import workflow

# Import our activity, passing it through the sandbox
with workflow.unsafe.imports_passed_through():
    from .activities import say_hello


@workflow.defn
class SayHello:
    """Temporal workflow class."""

    @workflow.run
    async def run(self, name: str) -> str:
        """Workflow execution method.

        Args:
            name: used to run the dynamic activity.

        Returns:
            Workflow execution
        """
        return await workflow.execute_activity(say_hello, name, schedule_to_close_timeout=timedelta(seconds=5))
