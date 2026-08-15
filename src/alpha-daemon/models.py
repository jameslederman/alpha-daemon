from dataclasses import dataclass
from typing import Literal
from pydantic import BaseModel
from datetime import datetime, date


class MarketEvent(BaseModel):
    symbol: str
    headline: str
    body: str


class Recommendation(BaseModel):
    symbol: str
    action: Literal["BUY", "HOLD", "SELL"]
    confidence: float
    rationale: str

@dataclass
class ResearchQuestion:
    question: str
    rationale: str
    priority: int


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
