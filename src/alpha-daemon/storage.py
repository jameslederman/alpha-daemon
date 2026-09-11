import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime

from models import EvidenceChunk, Filing
from pgvector.psycopg import register_vector_async
from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

CHUNK_EMBEDDINGS_SCHEMA = """
CREATE TABLE IF NOT EXISTS chunk_embeddings (
    chunk_id TEXT NOT NULL
        REFERENCES evidence_chunks(chunk_id)
        ON DELETE CASCADE,
    embedding_model TEXT NOT NULL,
    embedding VECTOR(512) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (chunk_id, embedding_model)
);
"""

EVIDENCE_CHUNKS_SCHEMA = """
CREATE TABLE IF NOT EXISTS evidence_chunks (
    chunk_id TEXT PRIMARY KEY,
    accession_number TEXT NOT NULL
        REFERENCES sec_filings(accession_number)
        ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    section TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    text TEXT NOT NULL,
    chunking_version TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

RESEARCH_RUNS_SCHEMA = """
CREATE TABLE IF NOT EXISTS research_runs (
    run_id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    as_of TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    status TEXT NOT NULL,
    result JSONB,
    error TEXT
);
"""

SEC_FILING_INVENTORY_SCHEMA = """
CREATE TABLE IF NOT EXISTS sec_filing_inventory (
    accession_number TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    cik TEXT NOT NULL,
    form TEXT NOT NULL,
    filed_at DATE NOT NULL,
    available_at TIMESTAMPTZ NOT NULL,
    primary_document TEXT NOT NULL,
    discovered_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

SEC_FILINGS_SCHEMA = """
CREATE TABLE IF NOT EXISTS sec_filings (
    accession_number TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    cik TEXT NOT NULL,
    form TEXT NOT NULL,
    filed_at DATE NOT NULL,
    available_at TIMESTAMPTZ NOT NULL,
    primary_document TEXT NOT NULL,
    source_url TEXT NOT NULL,
    raw_html TEXT NOT NULL,
    cleaned_text TEXT NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

VECTOR_EXTENSION_SCHEMA = """
CREATE EXTENSION IF NOT EXISTS vector;
"""


@asynccontextmanager
async def chunk_embedding_lock(
    chunk_id: str,
    embedding_model: str,
) -> AsyncGenerator[None, None]:
    lock_key = f"chunk_embedding:{chunk_id}:{embedding_model}"

    connection = await AsyncConnection.connect(
        os.environ["DATABASE_URL"],
        autocommit=True,
    )

    try:
        await connection.execute(
            """
            SELECT pg_advisory_lock(
                hashtextextended(%s, 0)
            )
            """,
            (lock_key,),
        )

        yield

    finally:
        await connection.execute(
            """
            SELECT pg_advisory_unlock(
                hashtextextended(%s, 0)
            )
            """,
            (lock_key,),
        )
        await connection.close()


async def initialize_storage() -> None:
    async with await AsyncConnection.connect(os.environ["DATABASE_URL"]) as connection:
        await connection.execute(CHUNK_EMBEDDINGS_SCHEMA)
        await connection.execute(EVIDENCE_CHUNKS_SCHEMA)
        await connection.execute(RESEARCH_RUNS_SCHEMA)
        await connection.execute(SEC_FILING_INVENTORY_SCHEMA)
        await connection.execute(SEC_FILINGS_SCHEMA)
        await connection.execute(VECTOR_EXTENSION_SCHEMA)


async def get_cached_sec_chunks_between(
    symbol: str,
    start: datetime,
    end: datetime,
    chunking_version: str,
) -> list[EvidenceChunk]:
    async with await AsyncConnection.connect(os.environ["DATABASE_URL"]) as connection:
        cursor = await connection.execute(
            """
            SELECT
                c.chunk_id,
                c.accession_number,
                c.symbol,
                f.source_url,
                f.filed_at,
                c.section,
                c.chunk_index,
                c.text
            FROM evidence_chunks AS c
            JOIN sec_filings AS f
                ON f.accession_number = c.accession_number
            WHERE c.symbol = %s
              AND f.available_at >= %s
              AND f.available_at <= %s
              AND c.chunking_version = %s
            ORDER BY f.available_at DESC, c.chunk_index
            """,
            (
                symbol.upper(),
                start,
                end,
                chunking_version,
            ),
        )

        rows = await cursor.fetchall()

    return [
        EvidenceChunk(
            chunk_id=row[0],
            symbol=row[2],
            source="sec_edgar",
            source_id=row[1],
            source_url=row[3],
            published_at=row[4],
            section=row[5],
            chunk_index=row[6],
            text=row[7],
        )
        for row in rows
    ]


async def get_cached_sec_accession_numbers(
    accession_numbers: list[str],
) -> set[str]:
    if not accession_numbers:
        return set()

    async with await AsyncConnection.connect(os.environ["DATABASE_URL"]) as connection:
        cursor = await connection.execute(
            """
            SELECT accession_number
            FROM sec_filings
            WHERE accession_number = ANY(%s)
            """,
            (accession_numbers,),
        )

        rows = await cursor.fetchall()

    return {row[0] for row in rows}


async def get_unmaterialized_sec_accessions_between(
    symbol: str,
    start: datetime,
    end: datetime,
    chunking_version: str,
) -> list[str]:
    async with await AsyncConnection.connect(os.environ["DATABASE_URL"]) as connection:
        cursor = await connection.execute(
            """
            SELECT i.accession_number
            FROM sec_filing_inventory AS i
            WHERE i.symbol = %s
              AND i.available_at >= %s
              AND i.available_at <= %s
              AND NOT EXISTS (
                  SELECT 1
                  FROM evidence_chunks AS c
                  WHERE c.accession_number = i.accession_number
                    AND c.chunking_version = %s
              )
            ORDER BY i.available_at DESC
            """,
            (
                symbol.upper(),
                start,
                end,
                chunking_version,
            ),
        )

        rows = await cursor.fetchall()

    return [row[0] for row in rows]


async def upsert_sec_filing(
    filing: Filing,
    source_url: str,
    raw_html: str,
    cleaned_text: str,
) -> None:
    async with await AsyncConnection.connect(os.environ["DATABASE_URL"]) as connection:
        await connection.execute(
            """
            INSERT INTO sec_filings (
                accession_number,
                symbol,
                cik,
                form,
                filed_at,
                available_at,
                primary_document,
                source_url,
                raw_html,
                cleaned_text
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (accession_number)
            DO UPDATE SET
                symbol = EXCLUDED.symbol,
                cik = EXCLUDED.cik,
                form = EXCLUDED.form,
                filed_at = EXCLUDED.filed_at,
                available_at = EXCLUDED.available_at,
                primary_document = EXCLUDED.primary_document,
                source_url = EXCLUDED.source_url,
                raw_html = EXCLUDED.raw_html,
                cleaned_text = EXCLUDED.cleaned_text,
                fetched_at = NOW()
            """,
            (
                filing.accession_number,
                filing.symbol,
                filing.cik,
                filing.form,
                filing.filed_at,
                filing.available_at,
                filing.primary_document,
                source_url,
                raw_html,
                cleaned_text,
            ),
        )


async def upsert_sec_filing_inventory(
    filings: list[Filing],
) -> None:
    if not filings:
        return

    rows = [
        (
            filing.accession_number,
            filing.symbol,
            filing.cik,
            filing.form,
            filing.filed_at,
            filing.available_at,
            filing.primary_document,
        )
        for filing in filings
    ]

    async with await AsyncConnection.connect(os.environ["DATABASE_URL"]) as connection:
        async with connection.cursor() as cursor:
            await cursor.executemany(
                """
                INSERT INTO sec_filing_inventory (
                    accession_number,
                    symbol,
                    cik,
                    form,
                    filed_at,
                    available_at,
                    primary_document
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (accession_number)
                DO UPDATE SET
                    symbol = EXCLUDED.symbol,
                    cik = EXCLUDED.cik,
                    form = EXCLUDED.form,
                    filed_at = EXCLUDED.filed_at,
                    available_at = EXCLUDED.available_at,
                    primary_document = EXCLUDED.primary_document,
                    discovered_at = NOW()
                """,
                rows,
            )


async def get_cached_chunk_embeddings(
    chunk_ids: list[str],
    embedding_model: str,
) -> dict[str, list[float]]:
    if not chunk_ids:
        return {}

    async with await AsyncConnection.connect(os.environ["DATABASE_URL"]) as connection:
        await register_vector_async(connection)

        cursor = await connection.execute(
            """
            SELECT chunk_id, embedding
            FROM chunk_embeddings
            WHERE embedding_model = %s
              AND chunk_id = ANY(%s)
            """,
            (
                embedding_model,
                chunk_ids,
            ),
        )

        rows = await cursor.fetchall()

    return {row[0]: list(row[1].to_list()) for row in rows}


async def get_cached_sec_chunks(
    accession_number: str,
    chunking_version: str,
) -> list[EvidenceChunk]:
    async with await AsyncConnection.connect(os.environ["DATABASE_URL"]) as connection:
        cursor = await connection.execute(
            """
            SELECT
                c.chunk_id,
                c.symbol,
                f.source_url,
                f.filed_at,
                c.section,
                c.chunk_index,
                c.text
            FROM evidence_chunks AS c
            JOIN sec_filings AS f
                ON f.accession_number = c.accession_number
            WHERE c.accession_number = %s
              AND c.chunking_version = %s
            ORDER BY c.chunk_id
            """,
            (
                accession_number,
                chunking_version,
            ),
        )

        rows = await cursor.fetchall()

    return [
        EvidenceChunk(
            chunk_id=row[0],
            symbol=row[1],
            source="sec_edgar",
            source_id=accession_number,
            source_url=row[2],
            published_at=row[3],
            section=row[4],
            chunk_index=row[5],
            text=row[6],
        )
        for row in rows
    ]


async def get_cached_sec_filing(
    accession_number: str,
) -> tuple[str, str] | None:
    async with await AsyncConnection.connect(os.environ["DATABASE_URL"]) as connection:
        cursor = await connection.execute(
            """
            SELECT raw_html, cleaned_text
            FROM sec_filings
            WHERE accession_number = %s
            """,
            (accession_number,),
        )

        row = await cursor.fetchone()

    if row is None:
        return None

    return row[0], row[1]


async def save_completed_research_run(
    run_id: str,
    symbol: str,
    as_of: datetime,
    created_at: datetime,
    result: dict,
) -> None:
    async with await AsyncConnection.connect(os.environ["DATABASE_URL"]) as connection:
        await connection.execute(
            """
            INSERT INTO research_runs (
                run_id,
                symbol,
                as_of,
                created_at,
                completed_at,
                status,
                result,
                error
            )
            VALUES (%s, %s, %s, %s, NOW(), 'completed', %s, NULL)
            ON CONFLICT (run_id)
            DO UPDATE SET
                completed_at = NOW(),
                status = 'completed',
                result = EXCLUDED.result,
                error = NULL
            """,
            (
                run_id,
                symbol.upper(),
                as_of,
                created_at,
                Jsonb(result),
            ),
        )


@asynccontextmanager
async def sec_chunk_lock(
    accession_number: str,
    chunking_version: str,
) -> AsyncGenerator[None, None]:
    lock_key = f"sec_chunks:{accession_number}:{chunking_version}"

    connection = await AsyncConnection.connect(
        os.environ["DATABASE_URL"],
        autocommit=True,
    )

    try:
        await connection.execute(
            """
            SELECT pg_advisory_lock(
                hashtextextended(%s, 0)
            )
            """,
            (lock_key,),
        )

        yield

    finally:
        await connection.execute(
            """
            SELECT pg_advisory_unlock(
                hashtextextended(%s, 0)
            )
            """,
            (lock_key,),
        )
        await connection.close()


@asynccontextmanager
async def sec_corpus_lock(
    symbol: str,
) -> AsyncGenerator[None, None]:
    connection = await AsyncConnection.connect(
        os.environ["DATABASE_URL"],
        autocommit=True,
    )

    lock_key = f"sec_corpus:{symbol.upper()}"

    try:
        await connection.execute(
            "SELECT pg_advisory_lock(hashtextextended(%s, 0))",
            (lock_key,),
        )
        yield
    finally:
        await connection.execute(
            "SELECT pg_advisory_unlock(hashtextextended(%s, 0))",
            (lock_key,),
        )
        await connection.close()


@asynccontextmanager
async def sec_filing_lock(
    accession_number: str,
) -> AsyncGenerator[None, None]:
    connection = await AsyncConnection.connect(
        os.environ["DATABASE_URL"],
        autocommit=True,
    )

    try:
        await connection.execute(
            """
            SELECT pg_advisory_lock(
                hashtextextended(%s, 0)
            )
            """,
            (accession_number,),
        )

        yield

    finally:
        await connection.execute(
            """
            SELECT pg_advisory_unlock(
                hashtextextended(%s, 0)
            )
            """,
            (accession_number,),
        )
        await connection.close()


async def upsert_evidence_chunks(
    chunks: list[EvidenceChunk],
    chunking_version: str,
) -> None:
    if not chunks:
        return

    rows = [
        (
            chunk.chunk_id,
            chunk.source_id,
            chunk.symbol,
            chunk.section,
            chunk.chunk_index,
            chunk.text,
            chunking_version,
        )
        for chunk in chunks
    ]

    async with await AsyncConnection.connect(os.environ["DATABASE_URL"]) as connection:
        async with connection.cursor() as cursor:
            await cursor.executemany(
                """
                INSERT INTO evidence_chunks (
                    chunk_id,
                    accession_number,
                    symbol,
                    section,
                    chunk_index,
                    text,
                    chunking_version
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (chunk_id)
                DO UPDATE SET
                    section = EXCLUDED.section,
                    chunk_index = EXCLUDED.chunk_index,
                    text = EXCLUDED.text,
                    chunking_version = EXCLUDED.chunking_version
                """,
                rows,
            )


async def upsert_chunk_embeddings(
    chunk_ids: list[str],
    embeddings: list[list[float]],
    embedding_model: str,
) -> None:
    if len(chunk_ids) != len(embeddings):
        raise ValueError("chunk_ids and embeddings must have the same length")

    if not chunk_ids:
        return

    rows = [
        (
            chunk_id,
            embedding_model,
            embedding,
        )
        for chunk_id, embedding in zip(
            chunk_ids,
            embeddings,
            strict=True,
        )
    ]

    async with await AsyncConnection.connect(os.environ["DATABASE_URL"]) as connection:
        await register_vector_async(connection)

        async with connection.cursor() as cursor:
            await cursor.executemany(
                """
                INSERT INTO chunk_embeddings (
                    chunk_id,
                    embedding_model,
                    embedding
                )
                VALUES (%s, %s, %s)
                ON CONFLICT (chunk_id, embedding_model)
                DO UPDATE SET
                    embedding = EXCLUDED.embedding
                """,
                rows,
            )
