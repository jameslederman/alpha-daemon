from datetime import timedelta

from temporalio import workflow
from temporalio.contrib.strands import TemporalAgent
from temporalio.contrib.strands.workflow import activity_as_tool

with workflow.unsafe.imports_passed_through():
    from activities import get_price_history_activity


@workflow.defn
class StrandsSmokeTestWorkflow:
    def __init__(self) -> None:
        self.agent = TemporalAgent(
            model="nova-pro",
            start_to_close_timeout=timedelta(seconds=60),
            tools=[
                activity_as_tool(
                    get_price_history_activity,
                    start_to_close_timeout=timedelta(seconds=30),
                )
            ],
        )

    @workflow.run
    async def run(self, prompt: str) -> str:
        result = await self.agent.invoke_async(prompt)
        return str(result)
