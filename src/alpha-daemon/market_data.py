from datetime import date, datetime
from typing import Protocol

from models import MarketBar, NewsArticle


class MarketDataProvider(Protocol):
    async def get_daily_bars(
        self,
        symbol: str,
        start: date,
        end: date,
    ) -> list[MarketBar]:
        ...

    async def get_news(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        limit: int = 100,
    ) -> list[NewsArticle]:
        ...