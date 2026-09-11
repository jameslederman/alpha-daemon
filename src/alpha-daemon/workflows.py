import asyncio
from datetime import timedelta

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from activities import (
        answer_question,
        fetch_market_events,
        plan_research,
        prepare_sec_corpus_activity,
        retrieve_evidence,
        save_completed_research_run_activity,
        synthesize_recommendation,
    )
    from fundamental_analyst import FundamentalAnalyst
    from models import (
        FundamentalAnalysis,
        Recommendation,
        ResearchRun,
    )


@workflow.defn
class ResearchWorkflow:
    @workflow.run
    async def run(
        self,
        run: ResearchRun,
    ) -> Recommendation:
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


@workflow.defn
class FundamentalAnalysisWorkflow:
    def __init__(self) -> None:
        self.analyst = FundamentalAnalyst()

    @workflow.run
    async def run(
        self,
        run: ResearchRun,
    ) -> FundamentalAnalysis:
        symbol = run.scope.attributes["symbol"]

        await workflow.execute_activity(
            prepare_sec_corpus_activity,
            args=[
                symbol,
                run.as_of - timedelta(days=3650),
                run.as_of,
                run.as_of - timedelta(days=730),
            ],
            start_to_close_timeout=timedelta(minutes=5),
        )

        result = await self.analyst.analyze(
            symbol=symbol,
            as_of=run.as_of,
        )

        await workflow.execute_activity(
            save_completed_research_run_activity,
            args=[
                run.run_id,
                symbol,
                run.as_of,
                run.created_at,
                result.model_dump(mode="json"),
            ],
            start_to_close_timeout=timedelta(seconds=30),
        )

        return result
