# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Preserve a workflow across a server refresh, then complete it and a new one.

Run with the integration-test Python environment before and after refresh:
  python tests/integration/temporal_client/upgrade_probe.py prepare HOST:7233
  python tests/integration/temporal_client/upgrade_probe.py verify HOST:7233
The namespace must already exist. Use --prefix for a separate test run.
"""

import argparse
import asyncio
from datetime import timedelta

from temporalio import activity, workflow
from temporalio.client import Client
from temporalio.worker import Worker


@activity.defn
async def echo(value: str) -> str:
    """Return a payload through the activity task queue."""
    return value


@workflow.defn
class UpgradeProbe:
    """Wait for a signal so the execution spans the database/server upgrade."""

    def __init__(self):
        self.finished = False

    @workflow.run
    async def run(self, wait_for_signal: bool) -> str:
        value = await workflow.execute_activity(echo, "preserved", start_to_close_timeout=timedelta(seconds=30))
        if wait_for_signal:
            await workflow.wait_condition(lambda: self.finished)
        return await workflow.execute_activity(echo, value, start_to_close_timeout=timedelta(seconds=30))

    @workflow.signal
    def finish(self):
        """Allow the pre-upgrade execution to finish after refresh."""
        self.finished = True

    @workflow.query
    def ready(self) -> bool:
        """Confirm a worker can process a workflow task."""
        return True


async def main():
    """Prepare or verify the test executions."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["prepare", "verify"])
    parser.add_argument("endpoint")
    parser.add_argument("--namespace", default="wf031-upgrade")
    parser.add_argument("--prefix", default="wf031-1.23-to-1.24")
    args = parser.parse_args()
    client = await Client.connect(args.endpoint, namespace=args.namespace)
    async with Worker(client, task_queue=args.prefix, workflows=[UpgradeProbe], activities=[echo]):
        if args.phase == "prepare":
            handle = await client.start_workflow(UpgradeProbe.run, True, id=args.prefix + "-existing", task_queue=args.prefix)
            assert await handle.query(UpgradeProbe.ready)
            print("Prepared running workflow:", handle.id, "run:", handle.first_execution_run_id, flush=True)
        else:
            handle = client.get_workflow_handle(args.prefix + "-existing")
            await handle.signal(UpgradeProbe.finish)
            assert await asyncio.wait_for(handle.result(), timeout=120) == "preserved"
            result = await client.execute_workflow(UpgradeProbe.run, False, id=args.prefix + "-new", task_queue=args.prefix)
            assert result == "preserved"
            history = await handle.fetch_history()
            print("PASS: existing workflow replayed and completed; new workflow/activity completed; history events:", len(history.events), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
