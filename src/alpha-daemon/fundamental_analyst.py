from datetime import datetime, timedelta

from temporalio import workflow
from temporalio.contrib.strands import TemporalAgent
from temporalio.contrib.strands.workflow import activity_as_tool

with workflow.unsafe.imports_passed_through():
    from activities import (
        get_price_history_activity,
        search_company_news_activity,
    )
    from models import FundamentalAnalysis

FUNDAMENTAL_ANALYST_SYSTEM_PROMPT = """
You are a fundamental equity research analyst.

Your job is to assess the underlying business and financial condition of a
company using evidence obtained through your available tools.

Focus on:
- revenue and earnings trends
- margins and operating performance
- cash flow and balance sheet strength
- management guidance
- capital allocation
- material company-specific developments
- risks that could materially affect future fundamentals

Rules:
- Use tools for factual claims about the company.
- Do not rely on prior knowledge for current facts.
- Distinguish evidence from inference.
- Do not make a BUY, HOLD, or SELL recommendation.
- Do not perform valuation or set a price target.
- Lower confidence when evidence is incomplete or conflicting.
"""


class FundamentalAnalyst:
    def __init__(self) -> None:
        self.agent = TemporalAgent(
            model="nova-pro",
            system_prompt=FUNDAMENTAL_ANALYST_SYSTEM_PROMPT,
            start_to_close_timeout=timedelta(seconds=60),
            structured_output_model=FundamentalAnalysis,
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

    async def analyze(
        self,
        symbol: str,
        as_of: datetime,
    ) -> FundamentalAnalysis:
        prompt = (
            f"Analyze the fundamentals of {symbol} as of {as_of.isoformat()}."
            "Gather the evidence you need using your available tools and return a"
            "fundamental analysis of the company."
        )

        result = await self.agent.invoke_async(prompt)

        assert isinstance(result.structured_output, FundamentalAnalysis)

        return result.structured_output
