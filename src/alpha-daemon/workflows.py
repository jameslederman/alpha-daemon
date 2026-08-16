from datetime import timedelta
from temporalio import workflow



with workflow.unsafe.imports_passed_through():
    from activities import fetch_market_events, analyze_events
    from models import MarketEvent, Recommendation, ResearchQuestion


@workflow.defn
class ResearchWorkflow:
    @workflow.run
    async def run(self, symbol: str) -> Recommendation:
        events = await workflow.execute_activity(
            "fetch_market_events",
            symbol,
            start_to_close_timeout=timedelta(seconds=30),
        )

        questions = await workflow.execute_activity(
            "plan_research",
            args=[symbol, events],
            start_to_close_timeout=timedelta(seconds=60),
        )

        evidence_chunks = await workflow.execute_activity(
            "retrieve_evidence",
            args=[events, questions],
            start_to_close_timeout=timedelta(minutes=10),
        )

        workflow.logger.info(f"Research questions: {questions}")

        recommendation = await workflow.execute_activity(
            "analyze_events",
            args=[evidence_chunks, questions],
            start_to_close_timeout=timedelta(seconds=60),
        )

        return recommendation