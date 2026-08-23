from market_data import MarketDataProvider
from models import (
    GetPriceHistoryArgs,
    MarketBar,
    NewsArticle,
    SearchCompanyNewsArgs,
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


async def search_company_news(
    args: SearchCompanyNewsArgs,
    provider: MarketDataProvider,
) -> list[NewsArticle]:
    return await provider.get_news(
        symbol=args.symbol,
        start=args.start,
        end=args.end,
        limit=args.limit,
    )
