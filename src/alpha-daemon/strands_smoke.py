from datetime import timedelta
from typing import Literal

from pydantic import BaseModel, Field
from temporalio import workflow
from temporalio.contrib.strands import TemporalAgent
from temporalio.contrib.strands.workflow import activity_as_tool

with workflow.unsafe.imports_passed_through():
    from activities import get_price_history_activity, search_company_news_activity


class PriceAnalysis(BaseModel):
    symbol: str
    trend: Literal["up", "down", "flat", "mixed"]
    summary: str
    notable_moves: list[str] = Field(default_factory=list)


@workflow.defn
class StrandsSmokeTestWorkflow:
    def __init__(self) -> None:
        self.agent = TemporalAgent(
            model="nova-pro",
            start_to_close_timeout=timedelta(seconds=60),
            structured_output_model=PriceAnalysis,
            tools=[
                activity_as_tool(
                    get_price_history_activity,
                    start_to_close_timeout=timedelta(seconds=30),
                ),
                activity_as_tool(
                    search_company_news_activity,
                    start_to_close_timeout=timedelta(seconds=30),
                ),
            ],
        )

    @workflow.run
    async def run(self, prompt: str) -> PriceAnalysis:
        result = await self.agent.invoke_async(prompt)
        assert isinstance(result.structured_output, PriceAnalysis)
        return result.structured_output
