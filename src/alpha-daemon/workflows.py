from datetime import timedelta
from temporalio import workflow



with workflow.unsafe.imports_passed_through():
    from activities import fetch_market_events, analyze_events
    from models import Recommendation


@workflow.defn
class ResearchWorkflow:
    @workflow.run
    async def run(self, symbol: str) -> Recommendation:
        events = await workflow.execute_activity(
            fetch_market_events,
            symbol,
            start_to_close_timeout=timedelta(seconds=30),
        )

        recommendation = await workflow.execute_activity(
            analyze_events,
            events,
            start_to_close_timeout=timedelta(seconds=60),
        )

        return recommendation