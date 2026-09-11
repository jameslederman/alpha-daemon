import json
from datetime import timedelta

from temporalio.contrib.strands import TemporalAgent

from models import (
    ResearchPlan,
    ResearchQuery,
    ResearchSynthesis,
    ResearchTask,
    ResearchTaskResult,
)
from research_skills import get_research_skill, list_research_skills


PLANNER_SYSTEM_PROMPT = """
You are AlphaDaemon's research planner.

Your job is to decompose a research objective into the smallest useful set of
specialized research tasks. Each task must use one of the registered skills
provided in the user prompt.

Rules:
- Use only registered skills.
- Create only tasks that materially help answer the objective.
- Prefer one focused task when one skill is sufficient.
- Use multiple tasks only when the objective genuinely spans multiple domains.
- Do not perform the research yourself.
- Do not invent tools or skills.
- Keep depends_on empty; task dependency scheduling is reserved for a later
  orchestration layer.
- Copy the supplied scope and as_of into each task. Infrastructure will validate
  them before execution.
"""


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
            structured_output_model=ResearchPlan,
            tools=[],
        )

    async def plan(self, query: ResearchQuery) -> ResearchPlan:
        skills = [
            {
                "name": skill.name,
                "description": skill.description,
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

Create a ResearchPlan that decomposes the objective into the minimum useful set
of specialist tasks.
"""

        result = await self.agent.invoke_async(prompt)
        plan = result.structured_output

        if not isinstance(plan, ResearchPlan):
            raise TypeError("Research planner returned an unexpected output type")

        if not plan.tasks:
            raise ValueError("Research planner returned no tasks")

        normalized_tasks: list[ResearchTask] = []
        for index, task in enumerate(plan.tasks, start=1):
            get_research_skill(task.skill)
            normalized_tasks.append(
                ResearchTask(
                    task_id=(
                        f"{query.query_id}:task:{index}:{task.skill}"
                    ),
                    skill=task.skill,
                    objective=task.objective,
                    scope=query.scope,
                    as_of=query.as_of,
                    depends_on=[],
                )
            )

        return ResearchPlan(
            objective=query.objective,
            tasks=normalized_tasks,
        )


class ResearchSynthesizer:
    def __init__(self) -> None:
        self.agent = TemporalAgent(
            model="nova-pro",
            system_prompt=SYNTHESIS_SYSTEM_PROMPT,
            start_to_close_timeout=timedelta(seconds=60),
            structured_output_model=ResearchSynthesis,
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

        if not isinstance(synthesis, ResearchSynthesis):
            raise TypeError("Research synthesizer returned an unexpected output type")

        if synthesis.query_id != query.query_id:
            synthesis = synthesis.model_copy(update={"query_id": query.query_id})

        return synthesis
