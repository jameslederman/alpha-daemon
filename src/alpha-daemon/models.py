from dataclasses import dataclass
from typing import Literal
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


class MarketEvent(BaseModel):
    symbol: str
    headline: str
    body: str
    source: str | None = None
    source_id: str | None = None
    source_url: str | None = None
    published_at: date | None = None


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


@dataclass(frozen=True)
class ResearchRequest:
    symbol: str
    as_of: datetime


class Filing(BaseModel):
    symbol: str
    cik: str
    accession_number: str
    form: str # 10K, 10-Q, 8K etc
    filed_at: date
    available_at: datetime
    primary_document: str


class ResearchScope(BaseModel):
    kind: str
    attributes: dict[str, str] = Field(default_factory=dict)


class ResearchRun(BaseModel):
    run_id: str
    scope: ResearchScope
    as_of: datetime
    created_at: datetime


class EvidenceMatch(BaseModel):
    chunk: EvidenceChunk

    tfidf_rank: int | None = None
    semantic_rank: int | None = None

    hybrid_rank: int
    rrf_score: float

    reranker_rank: int
    reranker_score: float


class QuestionEvidence(BaseModel):
    question: ResearchQuestion
    evidence: list[EvidenceMatch]


class ResearchFinding(BaseModel):
    finding_id: str
    question_id: str

    answer: str
    confidence: float

    evidence_ids: list[str]

    as_of: datetime
    created_at: datetime