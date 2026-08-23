import asyncio
import logging

from strands.models import BedrockModel
from temporalio import workflow
from temporalio.client import Client
from temporalio.contrib.strands import StrandsPlugin
from temporalio.worker import Worker

with workflow.unsafe.imports_passed_through():
    from activities import (
        answer_question,
        fetch_market_events,
        get_price_history_activity,
        plan_research,
        retrieve_evidence,
        synthesize_recommendation,
    )
    from strands_smoke import StrandsSmokeTestWorkflow
    from workflows import ResearchWorkflow


async def main():
    plugin = StrandsPlugin(
        models={
            "nova-pro": lambda: BedrockModel(
                model_id="amazon.nova-pro-v1:0",
            )
        }
    )

    client = await Client.connect(
        "localhost:7233",
        plugins=[plugin],
    )

    logging.basicConfig(level=logging.INFO)

    worker = Worker(
        client,
        task_queue="my-task-queue",
        workflows=[ResearchWorkflow, StrandsSmokeTestWorkflow],
        activities=[
            fetch_market_events,
            get_price_history_activity,
            plan_research,
            retrieve_evidence,
            answer_question,
            synthesize_recommendation,
        ],
    )
    print("Worker started.")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
