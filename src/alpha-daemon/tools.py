from market_data import MarketDataProvider
from models import (
    GetPriceHistoryArgs,
    MarketBar,
)


async def get_price_history(
    args: GetPriceHistoryArgs,
    provider: MarketDataProvider,
) -> list[MarketBar]:
    return await provider.get_daily_bars(
        symbol=args.symbol,
        start=args.start,
        end=args.end,
    )
