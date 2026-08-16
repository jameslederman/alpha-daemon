import json
import os
from temporalio import activity
from temporalio.exceptions import ApplicationError

from edgar import (get_latest_filing_event, NoRelevantFilingsError)
from llm import BedrockLLMClient
from models import (
    EvidenceChunk,
    MarketEvent,
    ResearchQuestion,
    Hypothesis,
    Evidence,
    Recommendation,
)
from retrieval import (
    chunk_sec_event,
    retrieve_for_queries,
)


@activity.defn
async def fetch_market_events(
    symbol: str,
) -> list[MarketEvent]:
    user_agent = os.environ["SEC_USER_AGENT"]

    try:
        filing_event = await get_latest_filing_event(
            symbol,
            user_agent=user_agent,
        )
    except NoRelevantFilingsError as exc:
        raise ApplicationError(
            str(exc),
            type="NoRelevantSECFilings",
            non_retryable=True,
        ) from exc

    return [filing_event]

@activity.defn
async def analyze_events(
    evidence_chunks: list[EvidenceChunk],
    questions: list[ResearchQuestion],
) -> Recommendation:
    if not evidence_chunks:
        raise ApplicationError(
            "No relevant evidence chunks found",
            type="NoRelevantEvidence",
            non_retryable=True,
        )

    symbol = evidence_chunks[0].symbol

    llm = BedrockLLMClient(
        model_id=os.getenv(
            "BEDROCK_MODEL_ID",
            "amazon.nova-pro-v1:0",
        )
    )

    evidence_text = "\n\n".join(
        f"Evidence ID: {chunk.chunk_id}\n"
        f"Section: {chunk.section}\n"
        f"Source: {chunk.source_url}\n"
        f"Text:\n{chunk.text}"
        for chunk in evidence_chunks
    )

    question_text = "\n".join(
        f"{question.priority}. {question.question}\n"
        f"   Why it matters: {question.rationale}"
        for question in questions
    )

    system_prompt = """
You are an evidence-constrained equity research analyst.

Evaluate the stock's 6-to-12-month fundamental outlook using only the supplied
evidence. Use the research questions as an analytical checklist.

Return only a JSON object conforming to this schema:

{
  "type": "object",
  "properties": {
    "action": {
      "type": "string",
      "enum": ["BUY", "HOLD", "SELL"]
    },
    "confidence": {
      "type": "number",
      "minimum": 0.0,
      "maximum": 1.0
    },
    "rationale": {
      "type": "string"
    }
  },
  "required": ["action", "confidence", "rationale"],
  "additionalProperties": false
}

Rules:
- action must be BUY, HOLD, or SELL.
- confidence must be between 0.0 and 1.0.
- Do not invent facts that are absent from the evidence.
- Distinguish facts from interpretations.
- Discuss material positive and negative evidence.
- Reduce confidence when important questions cannot be answered.
- Explain the key evidence and important limitations in the rationale.
- Reference the supporting evidence IDs in the rationale.
"""

    user_prompt = f"""
Symbol: {symbol}

Research questions:

{question_text}

Available evidence:

{evidence_text}
"""

    response = await llm.generate(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
    )

    activity.logger.info(
        "Analysis LLM call: "
        f"request_id={response.request_id}, "
        f"model={response.model_id}, "
        f"tokens={response.usage.total_tokens}, "
        f"latency_ms={response.latency_ms:.0f}"
    )

    data = json.loads(response.text)

    return Recommendation(
        symbol=symbol,
        action=data["action"],
        confidence=float(data["confidence"]),
        rationale=data["rationale"],
    )


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


@activity.defn
async def retrieve_evidence(
    events: list[MarketEvent],
    questions: list[ResearchQuestion],
) -> list[EvidenceChunk]:
    all_chunks = [
        chunk
        for event in events
        for chunk in chunk_sec_event(event)
    ]

    queries = [
        f"{question.question}\n{question.rationale}"
        for question in questions
    ]

    selected = retrieve_for_queries(
        queries=queries,
        chunks=[
            chunk.text
            for chunk in all_chunks
        ],
        top_k_per_query=2,
    )

    relevant_chunks = [
        all_chunks[result.index]
        for result in selected
    ]

    activity.logger.info(
        "Retrieved %d of %d evidence chunks",
        len(relevant_chunks),
        len(all_chunks),
    )

    return relevant_chunks
