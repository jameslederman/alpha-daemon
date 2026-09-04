import asyncio
import re
import time
from datetime import date, datetime, timezone

import httpx
from bs4 import BeautifulSoup
from models import Filing, MarketEvent
from storage import (
    get_cached_sec_filing,
    sec_filing_lock,
    upsert_sec_filing,
)

SEC_REQUEST_INTERVAL_SECONDS = 0.2  # 5 requests/second
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"

_sec_request_lock = asyncio.Lock()
_sec_last_request_at = 0.0


class NoRelevantFilingsError(Exception):
    pass


async def get_cik_for_ticker(
    ticker: str,
    user_agent: str,
) -> str:
    ticker = ticker.strip().upper()

    async with httpx.AsyncClient() as client:
        response = await sec_get(client, SEC_TICKERS_URL, user_agent)
        response.raise_for_status()
        companies = response.json()

    for company in companies.values():
        if company["ticker"].upper() == ticker:
            return str(company["cik_str"]).zfill(10)

    raise NoRelevantFilingsError(f"No relevant SEC filings found for {ticker}")


SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"

RESEARCH_FORMS = {"10-K", "10-Q", "8-K"}


def parse_sec_datetime(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))

    if dt.tzinfo is None:
        raise ValueError("SEC acceptance datetime must be timezone-aware")

    return dt


async def get_recent_filings(
    ticker: str,
    cik: str,
    user_agent: str,
) -> list[Filing]:
    url = SEC_SUBMISSIONS_URL.format(cik=cik.zfill(10))

    async with httpx.AsyncClient() as client:
        response = await sec_get(client, url, user_agent)
        response.raise_for_status()
        recent = response.json()["filings"]["recent"]

    filings: list[Filing] = []

    rows = zip(
        recent["accessionNumber"],
        recent["form"],
        recent["filingDate"],
        recent["acceptanceDateTime"],
        recent["primaryDocument"],
        strict=True,
    )

    for (
        accession_number,
        form,
        filed_at,
        available_at,
        primary_document,
    ) in rows:
        if form not in RESEARCH_FORMS:
            continue

        filings.append(
            Filing(
                symbol=ticker.upper(),
                cik=cik,
                accession_number=accession_number,
                form=form,
                filed_at=date.fromisoformat(filed_at),
                available_at=parse_sec_datetime(available_at),
                primary_document=primary_document,
            )
        )

    return parse_filings_block(
        ticker=ticker,
        cik=cik,
        data=recent,
    )


def get_filing_url(filing: Filing) -> str:
    cik = str(int(filing.cik))
    accession_number = filing.accession_number.replace("-", "")

    return (
        "https://www.sec.gov/Archives/edgar/data/"
        f"{cik}/{accession_number}/{filing.primary_document}"
    )


async def get_filing_document(
    filing: Filing,
    user_agent: str,
) -> str:
    cached = await get_cached_sec_filing(filing.accession_number)

    if cached is not None:
        raw_html, _ = cached
        return raw_html

    async with sec_filing_lock(filing.accession_number):
        cached = await get_cached_sec_filing(filing.accession_number)

        if cached is not None:
            raw_html, _ = cached
            return raw_html

        url = get_filing_url(filing)

        async with httpx.AsyncClient() as client:
            response = await sec_get(
                client,
                url,
                user_agent,
            )
            response.raise_for_status()

        raw_html = response.text
        cleaned_text = extract_filing_text(raw_html)

        await upsert_sec_filing(
            filing=filing,
            source_url=url,
            raw_html=raw_html,
            cleaned_text=cleaned_text,
        )

        return raw_html


async def get_filings_inventory(
    ticker: str,
    cik: str,
    user_agent: str,
    start: datetime,
    end: datetime,
) -> list[Filing]:
    url = SEC_SUBMISSIONS_URL.format(cik=cik.zfill(10))

    async with httpx.AsyncClient() as client:
        response = await sec_get(client, url, user_agent)
        response.raise_for_status()
        submissions = response.json()

        filings = parse_filings_block(
            ticker=ticker,
            cik=cik,
            data=submissions["filings"]["recent"],
        )

        for historical_file in submissions["filings"].get("files", []):
            filing_from = date.fromisoformat(historical_file["filingFrom"])
            filing_to = date.fromisoformat(historical_file["filingTo"])

            if filing_to < start.date():
                continue

            if filing_from > end.date():
                continue

            historical_url = (
                "https://data.sec.gov/submissions/" f"{historical_file['name']}"
            )

            historical_response = await sec_get(
                client,
                historical_url,
                user_agent,
            )
            historical_response.raise_for_status()

            filings.extend(
                parse_filings_block(
                    ticker=ticker,
                    cik=cik,
                    data=historical_response.json(),
                )
            )

    return [filing for filing in filings if start <= filing.available_at <= end]


def extract_filing_text(document: str) -> str:
    soup = BeautifulSoup(document, "html.parser")

    # Remove non-visible code and inline XBRL metadata.
    for element in soup.find_all(
        [
            "script",
            "style",
            "noscript",
            "ix:header",
            "ix:hidden",
            "ix:references",
            "ix:resources",
        ]
    ):
        element.decompose()

    # Remove HTML elements explicitly hidden by CSS.
    for element in soup.find_all(style=True):
        style = element.get("style", "")

        if not isinstance(style, str):
            continue

        normalized_style = style.lower().replace(" ", "")

        if "display:none" in normalized_style:
            element.decompose()

    raw_text = soup.get_text(separator="\n")

    cleaned_lines = []

    for line in raw_text.splitlines():
        line = re.sub(r"\s+", " ", line).strip()

        if line:
            cleaned_lines.append(line)

    return "\n".join(cleaned_lines)


async def get_filings_between(
    symbol: str,
    user_agent: str,
    start: datetime,
    end: datetime,
) -> list[Filing]:
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)

    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)

    cik = await get_cik_for_ticker(
        symbol,
        user_agent=user_agent,
    )

    filings = await get_filings_inventory(
        ticker=symbol,
        cik=cik,
        user_agent=user_agent,
        start=start,
        end=end,
    )

    return sorted(
        filings,
        key=lambda filing: filing.filed_at,
        reverse=True,
    )


async def get_filing_events_between(
    symbol: str,
    user_agent: str,
    start: datetime,
    end: datetime,
) -> list[MarketEvent]:
    filings = await get_filings_between(
        symbol=symbol,
        user_agent=user_agent,
        start=start,
        end=end,
    )

    documents = await asyncio.gather(
        *[
            get_filing_document(
                filing,
                user_agent=user_agent,
            )
            for filing in filings
        ]
    )

    return [
        filing_to_market_event(
            filing,
            extract_filing_text(document),
        )
        for filing, document in zip(
            filings,
            documents,
            strict=True,
        )
    ]


def filing_to_market_event(
    filing: Filing,
    filing_text: str,
) -> MarketEvent:
    return MarketEvent(
        symbol=filing.symbol,
        headline=(f"SEC {filing.form} filed on {filing.filed_at.isoformat()}"),
        body=filing_text,
        source="sec_edgar",
        source_id=filing.accession_number,
        source_url=get_filing_url(filing),
        published_at=filing.filed_at,
    )


# Orchestration function to get latest filing
async def get_latest_filing_event(
    symbol: str,
    user_agent: str,
    as_of: datetime,
) -> MarketEvent:
    cik = await get_cik_for_ticker(
        symbol,
        user_agent=user_agent,
    )

    filings = await get_recent_filings(
        ticker=symbol,
        cik=cik,
        user_agent=user_agent,
    )

    eligible_filings = [filing for filing in filings if filing.available_at <= as_of]

    if not eligible_filings:
        raise NoRelevantFilingsError(
            f"No relevant SEC filings found for {symbol}as of {as_of.isoformat()}"
        )

    filing = max(
        eligible_filings,
        key=lambda filing: filing.available_at,
    )

    document = await get_filing_document(
        filing,
        user_agent=user_agent,
    )

    filing_text = extract_filing_text(document)

    return filing_to_market_event(
        filing,
        filing_text,
    )


async def sec_get(
    client: httpx.AsyncClient,
    url: str,
    user_agent: str,
) -> httpx.Response:
    global _sec_last_request_at

    async with _sec_request_lock:
        now = time.monotonic()
        wait_seconds = _sec_last_request_at + SEC_REQUEST_INTERVAL_SECONDS - now

        if wait_seconds > 0:
            await asyncio.sleep(wait_seconds)

        response = await client.get(
            url,
            headers={"User-Agent": user_agent},
            timeout=30.0,
            follow_redirects=True,
        )

        _sec_last_request_at = time.monotonic()

    return response


def parse_filings_block(
    ticker: str,
    cik: str,
    data: dict,
) -> list[Filing]:
    filings: list[Filing] = []

    rows = zip(
        data["accessionNumber"],
        data["form"],
        data["filingDate"],
        data["acceptanceDateTime"],
        data["primaryDocument"],
        strict=True,
    )

    for (
        accession_number,
        form,
        filed_at,
        available_at,
        primary_document,
    ) in rows:
        if form not in RESEARCH_FORMS:
            continue

        filings.append(
            Filing(
                symbol=ticker.upper(),
                cik=cik,
                accession_number=accession_number,
                form=form,
                filed_at=date.fromisoformat(filed_at),
                available_at=parse_sec_datetime(available_at),
                primary_document=primary_document,
            )
        )

    return filings
