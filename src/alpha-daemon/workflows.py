import asyncio
from datetime import timedelta
from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from models import (
        Recommendation,
        ResearchRun,
    )
    from activities import (
        fetch_market_events,
        plan_research,
        retrieve_evidence,
        answer_question,
        synthesize_recommendation,
    )


@workflow.defn
class ResearchWorkflow:
    @workflow.run 
    async def run(self, run: ResearchRun,) -> Recommendation:
        events = await workflow.execute_activity(
            fetch_market_events,
            run,
            start_to_close_timeout=timedelta(seconds=30),
        )

        questions = await workflow.execute_activity(
            plan_research,
            args=[run, events],
            start_to_close_timeout=timedelta(seconds=60),
        )

        question_evidence = await workflow.execute_activity(
            retrieve_evidence,
            args=[events, questions],
            start_to_close_timeout=timedelta(minutes=10),
        )

        finding_handles = [
            workflow.start_activity(
                answer_question,
                question_evidence_item,
                start_to_close_timeout=timedelta(seconds=60),
            )
            for question_evidence_item in question_evidence
        ]
        findings = await asyncio.gather(*finding_handles)
        workflow.logger.info(
            "Research findings: %s",
            [finding.model_dump() for finding in findings],
        )
        # recommendation = await workflow.execute_activity(
        #     "analyze_events",
        #     args=[evidence_chunks, questions],
        #     start_to_close_timeout=timedelta(seconds=60),
        # )

        recommendation = await workflow.execute_activity(
            synthesize_recommendation,
            args=[run, findings],
            start_to_close_timeout=timedelta(seconds=60),
        )

        return recommendation