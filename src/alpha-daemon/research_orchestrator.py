import json
from datetime import timedelta

from models import (
    ResearchPlan,
    ResearchPlanDraft,
    ResearchQuery,
    ResearchSynthesis,
    ResearchSynthesisDraft,
    ResearchTask,
    ResearchTaskResult,
)
from research_skills import get_research_skill, list_research_skills
from temporalio.contrib.strands import TemporalAgent

MAX_RESEARCH_TASKS = 6


PLANNER_SYSTEM_PROMPT = f"""
You are AlphaDaemon's research planner.

Your job is to decompose a research objective into the smallest useful set of
specialized research tasks. Each task must use one of the registered skills
provided in the user prompt.

Rules:
- Use only registered skills.
- Create only tasks that materially help answer the objective.
- Prefer one focused task when one skill is sufficient.
- Use multiple tasks only when the objective genuinely spans multiple domains.
- Never create more than {MAX_RESEARCH_TASKS} tasks.
- Do not perform the research yourself.
- Do not invent tools or skills.
- For each task, specify only the skill and the focused research objective.
- Infrastructure owns task IDs, scope, point-in-time boundaries, and execution.
"""


class ResearchPlanValidationError(ValueError):
    """Planner output cannot be converted into an executable research plan."""


class ResearchSynthesisValidationError(ValueError):
    """Synthesizer output violates the ResearchSynthesis contract."""


SYNTHESIS_SYSTEM_PROMPT = """
You are AlphaDaemon's research synthesis agent.

Synthesize completed specialist research tasks into a direct answer to the
original research objective.

Rules:
- Use only the supplied task results.
- Preserve important disagreements, uncertainty, and coverage limitations.
- Distinguish conclusions from caveats.
- Do not claim that a specialist investigated something absent from its result.
- Confidence must reflect the quality and completeness of the supplied research.
- Do not introduce new factual claims from prior knowledge.
"""


class ResearchPlanner:
    def __init__(self) -> None:
        self.agent = TemporalAgent(
            model="nova-pro",
            system_prompt=PLANNER_SYSTEM_PROMPT,
            start_to_close_timeout=timedelta(seconds=60),
            structured_output_model=ResearchPlanDraft,
            tools=[],
        )

    async def plan(self, query: ResearchQuery) -> ResearchPlan:
        skills = [
            {
                "name": skill.name,
                "description": skill.description,
                "allowed_scope_kinds": skill.allowed_scope_kinds,
                "required_scope_attributes": skill.required_scope_attributes,
            }
            for skill in list_research_skills()
        ]

        prompt = f"""
Research query ID: {query.query_id}
As of: {query.as_of.isoformat()}
Scope: {json.dumps(query.scope.model_dump(mode="json"), sort_keys=True)}

Original research objective:
{query.objective}

Registered skills:
{json.dumps(skills, indent=2)}

Create a minimal ResearchPlanDraft containing the specialist tasks needed to
answer the objective.
"""

        result = await self.agent.invoke_async(prompt)
        draft = result.structured_output

        if not isinstance(draft, ResearchPlanDraft):
            raise ResearchPlanValidationError(
                "Research planner returned an unexpected output type"
            )

        if not draft.tasks:
            raise ResearchPlanValidationError("Research planner returned no tasks")

        if len(draft.tasks) > MAX_RESEARCH_TASKS:
            raise ResearchPlanValidationError(
                "Research planner returned too many tasks: "
                f"{len(draft.tasks)} > {MAX_RESEARCH_TASKS}"
            )

        tasks: list[ResearchTask] = []
        seen_tasks: set[tuple[str, str]] = set()

        for index, planned_task in enumerate(draft.tasks, start=1):
            skill_name = planned_task.skill.strip()
            objective = planned_task.objective.strip()

            if not skill_name:
                raise ResearchPlanValidationError(
                    f"Research planner returned a blank skill for task {index}"
                )

            if not objective:
                raise ResearchPlanValidationError(
                    f"Research planner returned a blank objective for task {index}"
                )

            try:
                skill = get_research_skill(skill_name)
                skill.validate_scope(query.scope)
            except ValueError as exc:
                raise ResearchPlanValidationError(str(exc)) from exc

            task_key = (skill_name, objective)
            if task_key in seen_tasks:
                raise ResearchPlanValidationError(
                    "Research planner returned a duplicate task: "
                    f"{skill_name!r} / {objective!r}"
                )
            seen_tasks.add(task_key)

            tasks.append(
                ResearchTask(
                    task_id=f"{query.query_id}:task:{index}:{skill_name}",
                    skill=skill_name,
                    objective=objective,
                    scope=query.scope,
                    as_of=query.as_of,
                    depends_on=[],
                )
            )

        return ResearchPlan(
            objective=query.objective,
            tasks=tasks,
        )


class ResearchSynthesizer:
    def __init__(self) -> None:
        self.agent = TemporalAgent(
            model="nova-pro",
            system_prompt=SYNTHESIS_SYSTEM_PROMPT,
            start_to_close_timeout=timedelta(seconds=60),
            structured_output_model=ResearchSynthesisDraft,
            tools=[],
        )

    async def synthesize(
        self,
        query: ResearchQuery,
        results: list[ResearchTaskResult],
    ) -> ResearchSynthesis:
        prompt = f"""
Research query ID: {query.query_id}
As of: {query.as_of.isoformat()}
Scope: {json.dumps(query.scope.model_dump(mode="json"), sort_keys=True)}

Original research objective:
{query.objective}

Completed specialist research:
{json.dumps([item.model_dump(mode="json") for item in results], indent=2)}

Synthesize the specialist results into the final ResearchSynthesis.
"""

        result = await self.agent.invoke_async(prompt)
        synthesis = result.structured_output

        if not isinstance(synthesis, ResearchSynthesisDraft):
            raise ResearchSynthesisValidationError(
                "Research synthesizer returned an unexpected output type"
            )

        return ResearchSynthesis(
            query_id=query.query_id,
            **synthesis.model_dump(),
        )
