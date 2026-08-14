from dataclasses import dataclass
from typing import Literal
from pydantic import BaseModel


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
    source_type: str
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