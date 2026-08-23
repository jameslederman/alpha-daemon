import asyncio
import logging
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.client import Client
from temporalio.worker import Worker
from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from workflows import ResearchWorkflow, ToolSmokeTestWorkflow
    from activities import (
        answer_question,
        execute_tool_activity,
        fetch_market_context,
        fetch_market_events,
        plan_research,
        retrieve_evidence,
        synthesize_recommendation,
    )

async def main():
    client = await Client.connect(
        "localhost:7233",
        data_converter=pydantic_data_converter,
    )

    logging.basicConfig(level=logging.INFO)
    
    worker = Worker(
        client,
        task_queue="my-task-queue",
        workflows=[ResearchWorkflow, ToolSmokeTestWorkflow],
        activities=[
            execute_tool_activity,
            fetch_market_context,
            fetch_market_events,
            plan_research,
            retrieve_evidence,
            answer_question,
            synthesize_recommendation,
        ]
    )
    print("Worker started.")
    await worker.run()

if __name__ == "__main__":
    asyncio.run(main())