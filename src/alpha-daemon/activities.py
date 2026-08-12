from temporalio import activity

from models import MarketEvent, Recommendation


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

