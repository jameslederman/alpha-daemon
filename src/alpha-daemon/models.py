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