import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.exceptions import ApplicationError

def _require_nonempty(value: str, field: str) -> None:
    if not value.strip():
        raise ApplicationError(
            f"{field} must not be blank",
            type="InvalidResearchInput",
            non_retryable=True,
        )


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
    from models import (
        FundamentalAnalysis,
        Recommendation,
        ResearchQuery,
        ResearchRun,
        ResearchSynthesis,
        ResearchTask,
        ResearchTaskResult,
    )
    from research_agent import ResearchAgent
    from research_orchestrator import ResearchPlanner, ResearchSynthesizer
    from research_skills import get_research_skill


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

        recommendation = await workflow.execute_activity(
            synthesize_recommendation,
            args=[run, findings],
            start_to_close_timeout=timedelta(seconds=60),
        )

        return recommendation


@workflow.defn
class ResearchTaskWorkflow:
    """Execute one skill-scoped research task using the generic research runtime."""

    @workflow.run
    async def run(
        self,
        task: ResearchTask,
    ) -> dict:
        _require_nonempty(task.skill, "task.skill")
        _require_nonempty(task.objective, "task.objective")

        try:
            skill = get_research_skill(task.skill)
            agent = ResearchAgent(skill)
            result = await agent.research(task)
        except (TypeError, ValueError) as exc:
            raise ApplicationError(
                str(exc),
                type="InvalidResearchTask",
                non_retryable=True,
            ) from exc

        return result.model_dump(mode="json")


@workflow.defn
class ResearchOrchestratorWorkflow:
    """Plan, execute, and synthesize a user- or agent-generated research query."""

    def __init__(self) -> None:
        self.planner = ResearchPlanner()
        self.synthesizer = ResearchSynthesizer()

    @workflow.run
    async def run(
        self,
        query: ResearchQuery,
    ) -> ResearchSynthesis:
        _require_nonempty(query.objective, "query.objective")

        try:
            plan = await self.planner.plan(query)
        except (TypeError, ValueError) as exc:
            raise ApplicationError(
                str(exc),
                type="InvalidResearchPlan",
                non_retryable=True,
            ) from exc

        outputs = await asyncio.gather(
            *[
                workflow.execute_child_workflow(
                    ResearchTaskWorkflow.run,
                    task,
                    id=task.task_id,
                )
                for task in plan.tasks
            ]
        )

        task_results = [
            ResearchTaskResult(
                task=task,
                result=output,
            )
            for task, output in zip(plan.tasks, outputs, strict=True)
        ]

        try:
            return await self.synthesizer.synthesize(
                query=query,
                results=task_results,
            )
        except (TypeError, ValueError) as exc:
            raise ApplicationError(
                str(exc),
                type="InvalidResearchSynthesis",
                non_retryable=True,
            ) from exc


@workflow.defn
class FundamentalAnalysisWorkflow:
    """Built-in fundamental-analysis workflow backed by the generic research agent."""

    @workflow.run
    async def run(
        self,
        run: ResearchRun,
    ) -> FundamentalAnalysis:
        symbol = run.scope.attributes["symbol"]
        skill = get_research_skill("fundamental_analysis")

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

        task = ResearchTask(
            task_id=f"{run.run_id}:fundamental_analysis",
            skill=skill.name,
            objective=skill.build_default_objective(run.scope),
            scope=run.scope,
            as_of=run.as_of,
        )

        result = await ResearchAgent(skill).research(task)

        if not isinstance(result, FundamentalAnalysis):
            raise TypeError(
                "fundamental_analysis skill returned an unexpected output type"
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
