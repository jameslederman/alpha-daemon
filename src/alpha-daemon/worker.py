import asyncio
import logging

from strands.models import BedrockModel
from temporalio import workflow
from temporalio.contrib.strands import StrandsPlugin
from temporalio.worker import Worker

with workflow.unsafe.imports_passed_through():
    from activities import (
        answer_question,
        fetch_market_events,
        get_price_history_activity,
        plan_research,
        prepare_sec_corpus_activity,
        retrieve_evidence,
        save_completed_research_run_activity,
        search_company_news_activity,
        search_sec_filings_activity,
        synthesize_recommendation,
    )
    from storage import initialize_storage
    from strands_smoke import StrandsSmokeTestWorkflow
    from temporal_runtime import connect_temporal_client, temporal_task_queue
    from workflows import (
        FundamentalAnalysisWorkflow,
        ResearchOrchestratorWorkflow,
        ResearchTaskWorkflow,
        ResearchWorkflow,
    )


async def main():
    plugin = StrandsPlugin(
        models={
            "nova-pro": lambda: BedrockModel(
                model_id="amazon.nova-pro-v1:0",
            )
        }
    )

    await initialize_storage()

    client = await connect_temporal_client(
        plugins=[plugin],
    )

    logging.basicConfig(level=logging.INFO)

    worker = Worker(
        client,
        task_queue=temporal_task_queue(),
        workflows=[
            FundamentalAnalysisWorkflow,
            ResearchOrchestratorWorkflow,
            ResearchTaskWorkflow,
            ResearchWorkflow,
            StrandsSmokeTestWorkflow,
        ],
        activities=[
            fetch_market_events,
            get_price_history_activity,
            search_company_news_activity,
            search_sec_filings_activity,
            prepare_sec_corpus_activity,
            plan_research,
            retrieve_evidence,
            save_completed_research_run_activity,
            answer_question,
            synthesize_recommendation,
        ],
    )
    print("Worker started.")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
