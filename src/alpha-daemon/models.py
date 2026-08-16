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
    # question_id: str
    question_key: str | None = None

    question: str
    rationale: str
    priority: int

    # as_of: datetime
    # created_at: datetime


@dataclass
class Evidence:
    source: str
    source_id: str
    claim: str
    relevance: str


@dataclass
class Hypothesis:
    symbol: str
    thesis: str
    supporting_evidence: list[Evidence]
    contradicting_evidence: list[Evidence]
    confidence: float


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
    primary_document: str


class ResearchScope(BaseModel):
    kind: str
    attributes: dict[str, str] = Field(default_factory=dict)


class ResearchRun(BaseModel):
    run_id: str
    scope: ResearchScope
    as_of: datetime
    created_at: datetime
