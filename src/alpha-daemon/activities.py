import json
import os
from datetime import datetime, timezone
from uuid import uuid4

from edgar import (
    Filing,
    NoRelevantFilingsError,
    get_latest_filing_event,
)
from llm import BedrockLLMClient
from massive import MassiveMarketDataProvider
from models import (
    EvidenceMatch,
    GetPriceHistoryArgs,
    MarketBar,
    MarketEvent,
    NewsArticle,
    QuestionEvidence,
    Recommendation,
    ResearchFinding,
    ResearchQuestion,
    ResearchRun,
    SearchCompanyNewsArgs,
    SearchSecFilingsArgs,
)
from retrieval import (
    chunk_sec_event,
    embed_chunks,
    load_reranker,
    rerank_chunks,
    retrieve_chunks,
    retrieve_chunks_hybrid,
    retrieve_chunks_semantic,
)
from temporalio import activity
from temporalio.exceptions import ApplicationError
from tools import (
    get_price_history,
    prepare_sec_corpus,
    search_company_news,
    search_sec_filings,
)


@activity.defn
async def fetch_market_events(
    run: ResearchRun,
) -> list[MarketEvent]:
    if run.scope.kind != "security":
        raise ApplicationError(
            f"Unsupported research scope: {run.scope.kind}",
            type="UnsupportedResearchScope",
            non_retryable=True,
        )

    symbol = run.scope.attributes.get("symbol")
    if not symbol:
        raise ApplicationError(
            "No symbol found in research scope",
            type="InvalidResearchScope",
            non_retryable=True,
        )

    user_agent = os.environ["SEC_USER_AGENT"]

    try:
        filing_event = await get_latest_filing_event(
            symbol,
            user_agent=user_agent,
            as_of=run.as_of,
        )
    except NoRelevantFilingsError as exc:
        raise ApplicationError(
            str(exc),
            type="NoRelevantSECFilings",
            non_retryable=True,
        ) from exc

    return [filing_event]


@activity.defn(name="get_price_history")
async def get_price_history_activity(
    symbol: str,
    start: str,
    end: str,
) -> list[MarketBar]:
    """Get daily historical OHLCV price data for a security over a date range."""

    provider = MassiveMarketDataProvider()

    args = GetPriceHistoryArgs(
        symbol=symbol,
        start=start,
        end=end,
    )

    return await get_price_history(
        args=args,
        provider=provider,
    )


@activity.defn(name="search_company_news")
async def search_company_news_activity(
    symbol: str,
    start: str,
    end: str,
    limit: int = 100,
) -> list[NewsArticle]:
    """Search for company news published over a date range."""

    provider = MassiveMarketDataProvider()

    args = SearchCompanyNewsArgs(
        symbol=symbol,
        start=start,
        end=end,
        limit=limit,
    )

    return await search_company_news(
        args=args,
        provider=provider,
    )


@activity.defn
async def plan_research(
    run: ResearchRun,
    events: list[MarketEvent],
) -> list[ResearchQuestion]:

    if run.scope.kind != "security":
        raise ApplicationError(
            f"Unsupported research scope: {run.scope.kind}",
            type="UnsupportedResearchScope",
            non_retryable=True,
        )

    symbol = run.scope.attributes.get("symbol")

    if not symbol:
        raise ApplicationError(
            "No symbol found in research scope",
            type="InvalidResearchScope",
            non_retryable=True,
        )

    llm = BedrockLLMClient(
        model_id=os.getenv(
            "BEDROCK_MODEL_ID",
            "amazon.nova-pro-v1:0",
        )
    )

    event_text = "\n\n".join(
        f"Headline: {event.headline}\nBody: {event.body}" for event in events
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

    questions_created_at = datetime.now(timezone.utc)

    questions = [
        ResearchQuestion(
            question_id=f"{run.run_id}:question:{uuid4()}",
            question_key=None,
            question=item["question"],
            rationale=item["rationale"],
            priority=item["priority"],
            as_of=run.as_of,
            created_at=questions_created_at,
        )
        for item in data["questions"]
    ]

    if not 3 <= len(questions) <= 5:
        raise ValueError(f"Expected 3-5 research questions, got {len(questions)}")

    priorities = [q.priority for q in questions]

    if len(priorities) != len(set(priorities)):
        raise ValueError("Research question priorities must be unique")

    return sorted(questions, key=lambda q: q.priority)


@activity.defn(name="prepare_sec_corpus")
async def prepare_sec_corpus_activity(
    symbol: str,
    start: datetime,
    end: datetime,
    materialize_start: datetime | None = None,
) -> list[Filing]:
    return await prepare_sec_corpus(
        symbol=symbol,
        start=start,
        end=end,
        materialize_start=materialize_start,
        user_agent=os.environ["SEC_USER_AGENT"],
    )


@activity.defn
async def retrieve_evidence(
    events: list[MarketEvent],
    questions: list[ResearchQuestion],
) -> list[QuestionEvidence]:
    all_chunks = [chunk for event in events for chunk in chunk_sec_event(event)]

    chunk_texts = [chunk.text for chunk in all_chunks]

    chunk_embeddings = embed_chunks(chunk_texts)

    reranker = load_reranker()

    question_evidence: list[QuestionEvidence] = []

    for question in questions:
        query = f"{question.question}\n{question.rationale}"

        tfidf_results = retrieve_chunks(
            query=query,
            chunks=chunk_texts,
            top_k=3,
        )

        semantic_results = retrieve_chunks_semantic(
            query=query,
            chunks=chunk_texts,
            chunk_embeddings=chunk_embeddings,
            top_k=3,
        )

        activity.logger.info(
            "\n\nQUESTION: %s",
            question.question,
        )

        activity.logger.info("\nTF-IDF RESULTS:")

        for result in tfidf_results:
            chunk = all_chunks[result.index]

            activity.logger.info(
                "\n%s\nSection: %s\nScore: %.3f\n%s",
                chunk.chunk_id,
                chunk.section,
                result.score,
                chunk.text[:500],
            )

        activity.logger.info("\nSEMANTIC RESULTS:")

        for result in semantic_results:
            chunk = all_chunks[result.index]

            activity.logger.info(
                "\n%s\nSection: %s\nScore: %.3f\n%s",
                chunk.chunk_id,
                chunk.section,
                result.score,
                chunk.text[:500],
            )

        hybrid_results = retrieve_chunks_hybrid(
            query=query,
            chunks=chunk_texts,
            chunk_embeddings=chunk_embeddings,
            top_k_per_method=5,
            top_k=5,
        )

        activity.logger.info("\nHYBRID RESULTS:")

        for result in hybrid_results:
            chunk = all_chunks[result.index]

            activity.logger.info(
                "\n%s"
                "\nSection: %s"
                "\nRRF Score: %.5f"
                "\nTF-IDF rank: %s"
                "\nSemantic rank: %s"
                "\n%s",
                chunk.chunk_id,
                chunk.section,
                result.score,
                result.tfidf_rank,
                result.semantic_rank,
                chunk.text[:500],
            )

        reranked_results = rerank_chunks(
            query=query,
            candidates=hybrid_results,
            reranker=reranker,
            top_k=3,
        )

        activity.logger.info("\nRERANKED RESULTS:")

        for result in reranked_results:
            chunk = all_chunks[result.index]

            activity.logger.info(
                "\n%s\nSection: %s\nReranker score: %.3f\n%s",
                chunk.chunk_id,
                chunk.section,
                result.score,
                chunk.text[:500],
            )

        hybrid_by_index = {
            result.index: (rank, result)
            for rank, result in enumerate(
                hybrid_results,
                start=1,
            )
        }

        matches: list[EvidenceMatch] = []
        for reranker_rank, result in enumerate(
            reranked_results,
            start=1,
        ):
            hybrid_rank, hybrid_result = hybrid_by_index[result.index]

            matches.append(
                EvidenceMatch(
                    chunk=all_chunks[result.index],
                    tfidf_rank=hybrid_result.tfidf_rank,
                    semantic_rank=hybrid_result.semantic_rank,
                    hybrid_rank=hybrid_rank,
                    rrf_score=hybrid_result.score,
                    reranker_rank=reranker_rank,
                    reranker_score=result.score,
                )
            )

        question_evidence.append(
            QuestionEvidence(
                question=question,
                evidence=matches,
            )
        )
        activity.logger.info(
            "Retrieved evidence for %d research questions",
            len(question_evidence),
        )

    return question_evidence


@activity.defn
async def answer_question(
    question_evidence: QuestionEvidence,
) -> ResearchFinding:
    question = question_evidence.question

    if not question_evidence.evidence:
        raise ApplicationError(
            f"No evidence found for question {question.question_id}",
            type="NoQuestionEvidence",
            non_retryable=True,
        )

    llm = BedrockLLMClient(
        model_id=os.getenv(
            "BEDROCK_MODEL_ID",
            "amazon.nova-pro-v1:0",
        )
    )

    evidence_text = "\n\n".join(
        f"Evidence ID: {match.chunk.chunk_id}\n"
        f"Section: {match.chunk.section}\n"
        f"Source: {match.chunk.source_url}\n"
        f"Text:\n{match.chunk.text}"
        for match in question_evidence.evidence
    )

    system_prompt = """
You are an evidence-constrained financial research analyst.

Answer one research question using only the supplied evidence.

Return only valid JSON in this format:

{
  "answer": "string",
  "confidence": 0.0,
  "evidence_ids": ["string"]
}

Rules:
- Answer the research question directly.
- Do not make a BUY, HOLD, or SELL recommendation.
- Do not invent facts absent from the evidence.
- confidence must be between 0.0 and 1.0.
- evidence_ids must contain only IDs from the supplied evidence.
- Include only evidence that materially supports the answer.
- Lower confidence when the evidence is incomplete or conflicting.
"""

    user_prompt = f"""
Research question:
{question.question}

Why it matters:
{question.rationale}

Evidence:
{evidence_text}
"""

    response = await llm.generate(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
    )

    data = json.loads(response.text)

    valid_evidence_ids = {match.chunk.chunk_id for match in question_evidence.evidence}

    returned_evidence_ids = data["evidence_ids"]

    if not set(returned_evidence_ids).issubset(valid_evidence_ids):
        raise ValueError("Finding referenced evidence that was not supplied")

    confidence = float(data["confidence"])

    if not 0.0 <= confidence <= 1.0:
        raise ValueError(f"Invalid finding confidence: {confidence}")

    created_at = datetime.now(timezone.utc)

    finding = ResearchFinding(
        finding_id=(f"{question.question_id}:finding:{uuid4()}"),
        question_id=question.question_id,
        answer=data["answer"],
        confidence=confidence,
        evidence_ids=returned_evidence_ids,
        as_of=question.as_of,
        created_at=created_at,
    )

    activity.logger.info(
        "Research finding: question_id=%s "
        "confidence=%.2f evidence_count=%d "
        "tokens=%d latency_ms=%.0f",
        question.question_id,
        finding.confidence,
        len(finding.evidence_ids),
        response.usage.total_tokens,
        response.latency_ms,
    )

    return finding


@activity.defn(name="search_sec_filings")
async def search_sec_filings_activity(
    symbol: str,
    query: str,
    start: str,
    end: str,
    limit: int = 5,
) -> list[EvidenceMatch]:
    """Search SEC filings for evidence relevant to a fundamental research question."""

    args = SearchSecFilingsArgs(
        symbol=symbol,
        query=query,
        start=start,
        end=end,
        limit=limit,
    )

    return await search_sec_filings(
        args=args,
    )


@activity.defn
async def synthesize_recommendation(
    run: ResearchRun,
    findings: list[ResearchFinding],
) -> Recommendation:
    if not findings:
        raise ApplicationError(
            "No research findings available",
            type="NoResearchFindings",
            non_retryable=True,
        )

    if run.scope.kind != "security":
        raise ApplicationError(
            f"Unsupported research scope: {run.scope.kind}",
            type="UnsupportedResearchScope",
            non_retryable=True,
        )

    symbol = run.scope.attributes.get("symbol")

    if not symbol:
        raise ApplicationError(
            "No symbol found in research scope",
            type="InvalidResearchScope",
            non_retryable=True,
        )

    llm = BedrockLLMClient(
        model_id=os.getenv(
            "BEDROCK_MODEL_ID",
            "amazon.nova-pro-v1:0",
        )
    )

    findings_text = "\n\n".join(
        f"Finding ID: {finding.finding_id}\n"
        f"Question ID: {finding.question_id}\n"
        f"Confidence: {finding.confidence:.2f}\n"
        f"Evidence IDs: {', '.join(finding.evidence_ids)}\n"
        f"Finding:\n{finding.answer}"
        for finding in findings
    )

    system_prompt = """
You are an evidence-constrained equity research analyst.

Synthesize the supplied research findings into a 6-to-12-month
fundamental investment recommendation.

Return only valid JSON in this format:

{
  "action": "BUY",
  "confidence": 0.0,
  "rationale": "string"
}

Rules:
- action must be BUY, HOLD, or SELL.
- confidence must be between 0.0 and 1.0.
- Use only the supplied research findings.
- Do not invent facts.
- Consider both positive and negative findings.
- Weight findings according to their confidence and materiality.
- Reduce confidence when findings are incomplete, uncertain, or conflicting.
- Explain the most important drivers of the recommendation.
- Reference supporting evidence IDs in the rationale.
"""

    user_prompt = f"""
Symbol: {symbol}

Research findings:

{findings_text}
"""

    response = await llm.generate(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
    )

    data = json.loads(response.text)

    confidence = float(data["confidence"])

    if not 0.0 <= confidence <= 1.0:
        raise ValueError(f"Invalid recommendation confidence: {confidence}")

    recommendation = Recommendation(
        symbol=symbol,
        action=data["action"],
        confidence=confidence,
        rationale=data["rationale"],
    )

    activity.logger.info(
        "Recommendation synthesis: symbol=%s "
        "findings=%d confidence=%.2f "
        "tokens=%d latency_ms=%.0f",
        symbol,
        len(findings),
        recommendation.confidence,
        response.usage.total_tokens,
        response.latency_ms,
    )

    return recommendation
