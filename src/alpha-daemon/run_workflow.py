from temporalio.contrib.pydantic import pydantic_data_converter
import asyncio
from temporalio.client import Client
from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from workflows import ResearchWorkflow

async def main():
    # Connect client to the local temporal server
    client = await Client.connect(
        "localhost:7233",
        data_converter=pydantic_data_converter,
    )

    # Execute the workflow
    result = await client.execute_workflow(
        ResearchWorkflow.run,
        "AAPL",
        id="research-symbol-workflow",
        task_queue="my-task-queue",
    )

    print(f"Workflow result: {result}")

if __name__ == "__main__":
    asyncio.run(main())
