# Import the activity and workflow from our other files
from .activities import say_hello
from temporalio.client import Client
from temporalio.worker import Worker
from .workflows import SayHello
import asyncio

async def run_worker(url):
    client = await Client.connect(url)
    
    # Run the worker
    worker = Worker(client, task_queue="my-task-queue", workflows=[SayHello], activities=[say_hello])
    await worker.run()

def sync_run_worker(url):
    asyncio.run(run_worker(url))