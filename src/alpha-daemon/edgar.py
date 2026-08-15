from bs4 import BeautifulSoup
from datetime import date
import httpx
import re


from models import Filing, MarketEvent

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"

class NoRelevantFilingsError(Exception):
    pass

async def get_cik_for_ticker(
    ticker: str,
    user_agent: str,
) -> str:
    ticker = ticker.strip().upper()

    async with httpx.AsyncClient() as client:
        response = await client.get(
            SEC_TICKERS_URL,
            headers={"User-Agent": user_agent},
            timeout=30.0,
        )
        response.raise_for_status()
        companies = response.json()

    for company in companies.values():
        if company["ticker"].upper() == ticker:
            return str(company["cik_str"]).zfill(10)

    raise NoRelevantFilingsError(
        f"No relevant SEC filings found for {ticker}"
    )


SEC_SUBMISSIONS_URL = (
    "https://data.sec.gov/submissions/CIK{cik}.json"
)

RESEARCH_FORMS = {"10-K", "10-Q", "8-K"}


async def get_recent_filings(
    ticker: str,
    cik: str,
    user_agent: str,
) -> list[Filing]:
    url = SEC_SUBMISSIONS_URL.format(cik=cik.zfill(10))

    async with httpx.AsyncClient() as client:
        response = await client.get(
            url,
            headers={"User-Agent": user_agent},
            timeout=30.0,
        )
        response.raise_for_status()
        recent = response.json()["filings"]["recent"]

    filings: list[Filing] = []

    rows = zip(
        recent["accessionNumber"],
        recent["form"],
        recent["filingDate"],
        recent["primaryDocument"],
        strict=True,
    )

    for accession_number, form, filed_at, primary_document in rows:
        if form not in RESEARCH_FORMS:
            continue

        filings.append(
            Filing(
                symbol=ticker.upper(),
                cik=cik,
                accession_number=accession_number,
                form=form,
                filed_at=date.fromisoformat(filed_at),
                primary_document=primary_document,
            )
        )

    return filings


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
    url = get_filing_url(filing)

    async with httpx.AsyncClient() as client:
        response = await client.get(
            url,
            headers={"User-Agent": user_agent},
            timeout=30.0,
            follow_redirects=True,
        )
        response.raise_for_status()

    return response.text

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


def filing_to_market_event(
    filing: Filing,
    filing_text: str,
) -> MarketEvent:
    return MarketEvent(
        symbol=filing.symbol,
        headline=(
            f"SEC {filing.form} filed on "
            f"{filing.filed_at.isoformat()}"
        ),
        body=filing_text,
    )

# Orchestration function to get latest filing
async def get_latest_filing_event(
    symbol: str,
    user_agent: str,
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

    if not filings:
        raise ValueError(
            f"No relevant SEC filings found for {symbol}"
        )

    filing = filings[0]

    document = await get_filing_document(
        filing,
        user_agent=user_agent,
    )

    filing_text = extract_filing_text(document)

    return filing_to_market_event(
        filing,
        filing_text,
    )


###############################################################################
# this test runs when you execute edgar.py directly, but not later when activities.py imports get_cik_for_ticker
import asyncio

async def main() -> None:
    event = await get_latest_filing_event(
        "SPY",
        user_agent = "AlphaDaemon james.lederman@gmail.com"
    )

    print(event.headline)
    print(f"Body characters: {len(event.body):,}")
    print(event.body[:1_000])

if __name__ == "__main__":
    asyncio.run(main())