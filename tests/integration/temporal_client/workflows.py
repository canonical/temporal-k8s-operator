# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.


"""Temporal client sample workflow."""

import asyncio
from datetime import timedelta
from typing import List

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


@workflow.defn
class GreetingWorkflow:
    """Temporal workflow class."""

    def __init__(self) -> None:
        """Construct."""
        self._pending_greetings: asyncio.Queue[str] = asyncio.Queue()
        self._exit = False

    @workflow.run
    async def run(self) -> List[str]:
        """Workflow execution method.

        Returns:
            Workflow execution result.
        """
        # Continually handle from queue or wait for exit to be received
        greetings: List[str] = []
        while True:
            # Wait for queue item or exit
            await workflow.wait_condition(lambda: not self._pending_greetings.empty() or self._exit)

            # Drain and process queue
            while not self._pending_greetings.empty():
                greetings.append(f"Hello, {self._pending_greetings.get_nowait()}")

            # Exit if complete
            if self._exit:
                return greetings

    @workflow.signal
    async def submit_greeting(self, name: str) -> None:
        """Workflow signal method.

        Args:
            name: inserted into the dynamic workflow list.
        """
        await self._pending_greetings.put(name)

    @workflow.signal
    def exit(self) -> None:
        """Workflow exit signal method."""
        self._exit = True
