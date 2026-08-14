import json
import os

from temporalio import activity

from llm import BedrockLLMClient
from models import MarketEvent, ResearchQuestion, Hypothesis, Evidence, Recommendation


@activity.defn
async def fetch_market_events(symbol: str) -> list[MarketEvent]:
    # Mock data - replace with actual API calls
    return [
        MarketEvent(
            symbol=symbol,
            headline=f"{symbol} earnings beat expectations",
            body=f"Company X reported Q2 earnings that exceeded analyst estimates...",
        ),
        MarketEvent(
            symbol=symbol,
            headline=f"Analyst upgrades {symbol}",
            body=f"Goldman Sachs upgraded {symbol} to 'Buy'...",
        ),
    ]


@activity.defn
async def analyze_events(events: list[MarketEvent]) -> Recommendation:
    symbol = events[0].symbol
    action = "BUY"
    confidence = 0.9
    rationale = f"Based on {len(events)} positive news events, recommending BUY."
    return Recommendation(symbol=symbol, action=action, confidence=confidence, rationale=rationale)


@activity.defn
async def plan_research(
    symbol: str,
    events: list[MarketEvent],
) -> list[ResearchQuestion]:
    llm = BedrockLLMClient(
        model_id=os.getenv(
            "BEDROCK_MODEL_ID",
            "amazon.nova-pro-v1:0",
        )
    )

    event_text = "\n\n".join(
        f"Headline: {event.headline}\n"
        f"Body: {event.body}"
        for event in events
    )

    system_prompt = """
You are planning financial research for an investment analysis system.

Given a stock symbol and recent market events, identify the most important
questions that should be investigated before forming an investment thesis.

Return ONLY valid JSON in this format:

{
  "questions": [
    {
      "question": "string",
      "rationale": "string",
      "priority": 1
    }
  ]
}

Rules:
- Generate 3 to 5 questions.
- Questions should be specific and answerable through financial research.
- Prefer questions whose answers could materially change the investment thesis.
- Do not answer the questions.
- Avoid generic questions such as "Is the company a good investment?"
- priority=1 means highest priority.
- Each priority must be unique.
"""

    user_prompt = f"""
Symbol: {symbol}

Recent events:

{event_text}
"""

    response = await llm.generate(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
    )

    activity.logger.info(
        "Research planning LLM call: "
        f"request_id={response.request_id}, "
        f"model={response.model_id}, "
        f"tokens={response.usage.total_tokens}, "
        f"latency_ms={response.latency_ms:.0f}"
    )

    data = json.loads(response.text)

    questions = [
        ResearchQuestion(
            question=item["question"],
            rationale=item["rationale"],
            priority=item["priority"],
        )
        for item in data["questions"]
    ]

    if not 3 <= len(questions) <= 5:
        raise ValueError(
            f"Expected 3-5 research questions, got {len(questions)}"
        )

    priorities = [q.priority for q in questions]

    if len(priorities) != len(set(priorities)):
        raise ValueError("Research question priorities must be unique")

    return sorted(questions, key=lambda q: q.priority)