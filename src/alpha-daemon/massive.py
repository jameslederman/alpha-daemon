import os
from datetime import date, datetime, timezone

import httpx
from models import MarketBar, NewsArticle


class MassiveMarketDataProvider:
    BASE_URL = "https://api.massive.com"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ["MASSIVE_API_KEY"]

    async def get_daily_bars(
        self,
        symbol: str,
        start: date,
        end: date,
    ) -> list[MarketBar]:
        url = (
            f"{self.BASE_URL}/v2/aggs/ticker/{symbol.upper()}"
            f"/range/1/day/{start.isoformat()}/{end.isoformat()}"
        )

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                url,
                headers={"Authorization": f"Bearer {self.api_key}"},
                params={
                    "adjusted": "true",
                    "sort": "asc",
                },
            )
            response.raise_for_status()

        data = response.json()

        return [
            MarketBar(
                symbol=symbol.upper(),
                timestamp=datetime.fromtimestamp(
                    result["t"] / 1000,
                    tz=timezone.utc,
                ),
                open=result["o"],
                high=result["h"],
                low=result["l"],
                close=result["c"],
                volume=result["v"],
                vwap=result.get("vw"),
                transactions=result.get("n"),
            )
            for result in data.get("results", [])
        ]

    async def get_news(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        limit: int = 100,
    ) -> list[NewsArticle]:
        url = f"{self.BASE_URL}/v2/reference/news"

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                url,
                headers={"Authorization": f"Bearer {self.api_key}"},
                params={
                    "ticker": symbol.upper(),
                    "published_utc.gte": start.isoformat(),
                    "published_utc.lte": end.isoformat(),
                    "sort": "published_utc",
                    "order": "desc",
                    "limit": limit,
                },
            )
            response.raise_for_status()

        data = response.json()

        return [
            NewsArticle(
                article_id=result["id"],
                headline=result["title"],
                description=result.get("description"),
                publisher=result["publisher"]["name"],
                author=result.get("author"),
                published_at=datetime.fromisoformat(
                    result["published_utc"].replace("Z", "+00:00")
                ),
                article_url=result["article_url"],
                symbols=result.get("tickers", []),
                keywords=result.get("keywords", []),
            )
            for result in data.get("results", [])
        ]
