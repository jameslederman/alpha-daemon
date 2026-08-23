from dataclasses import dataclass
from typing import Any, Literal
from pydantic import BaseModel, Field
from datetime import datetime, date


class EvidenceChunk(BaseModel):
    chunk_id: str
    symbol: str
    source: str
    source_id: str
    source_url: str | None
    published_at: date | None
    section: str
    chunk_index: int
    text: str


class EvidenceMatch(BaseModel):
    chunk: EvidenceChunk

    tfidf_rank: int | None = None
    semantic_rank: int | None = None

    hybrid_rank: int
    rrf_score: float

    reranker_rank: int
    reranker_score: float


class Filing(BaseModel):
    symbol: str
    cik: str
    accession_number: str
    form: str # 10K, 10-Q, 8K etc
    filed_at: date
    available_at: datetime
    primary_document: str


class GetPriceHistoryArgs(BaseModel):
    symbol: str
    start: date
    end: date


class MarketBar(BaseModel):
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    vwap: float | None = None
    transactions: int | None = None


class MarketContext(BaseModel):
    symbol: str
    as_of: datetime
    daily_bars: list[MarketBar] = Field(default_factory=list)
    news: list[NewsArticle] = Field(default_factory=list)


class MarketEvent(BaseModel):
    symbol: str
    headline: str
    body: str
    source: str | None = None
    source_id: str | None = None
    source_url: str | None = None
    published_at: date | None = None


class NewsArticle(BaseModel):
    article_id: str
    headline: str
    description: str | None = None
    publisher: str
    author: str | None = None
    published_at: datetime
    article_url: str
    symbols: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)


class QuestionEvidence(BaseModel):
    question: ResearchQuestion
    evidence: list[EvidenceMatch]


class Recommendation(BaseModel):
    symbol: str
    action: Literal["BUY", "HOLD", "SELL"]
    confidence: float
    rationale: str


class ResearchQuestion(BaseModel):
    question_id: str
    question_key: str | None = None

    question: str
    rationale: str
    priority: int

    as_of: datetime
    created_at: datetime


class ResearchFinding(BaseModel):
    finding_id: str
    question_id: str

    answer: str
    confidence: float

    evidence_ids: list[str]

    as_of: datetime
    created_at: datetime


@dataclass(frozen=True)
class ResearchRequest:
    symbol: str
    as_of: datetime


class ResearchRun(BaseModel):
    run_id: str
    scope: ResearchScope
    as_of: datetime
    created_at: datetime


class ResearchScope(BaseModel):
    kind: str
    attributes: dict[str, str] = Field(default_factory=dict)


class ToolRequest(BaseModel):
    call_id: str
    tool_name: str
    arguments: dict[str, Any]


class ToolResult(BaseModel):
    call_id: str
    tool_name: str
    output: Any
