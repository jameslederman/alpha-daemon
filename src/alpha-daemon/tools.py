from datetime import datetime

import numpy as np
from edgar import (
    extract_filing_text,
    filing_to_market_event,
    get_filing_document,
    get_filings_between,
)
from market_data import MarketDataProvider
from models import (
    EvidenceMatch,
    Filing,
    GetPriceHistoryArgs,
    MarketBar,
    NewsArticle,
    SearchCompanyNewsArgs,
    SearchSecFilingsArgs,
)
from retrieval import (
    EMBEDDING_MODEL_ID,
    SEC_CHUNKING_VERSION,
    chunk_sec_event,
    embed_text,
    load_reranker,
    rerank_chunks,
    retrieve_chunks_hybrid,
)
from storage import (
    chunk_embedding_lock,
    get_cached_chunk_embeddings,
    get_cached_sec_chunks,
    get_cached_sec_chunks_between,
    get_unmaterialized_sec_accessions_between,
    sec_chunk_lock,
    upsert_chunk_embeddings,
    upsert_evidence_chunks,
    upsert_sec_filing_inventory,
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


async def prepare_sec_corpus(
    symbol: str,
    start: datetime,
    end: datetime,
    user_agent: str,
    materialize_start: datetime | None = None,
) -> list[Filing]:
    filings = await get_filings_between(
        symbol=symbol,
        user_agent=user_agent,
        start=start,
        end=end,
    )

    await upsert_sec_filing_inventory(filings)

    if materialize_start is None:
        materialize_start = start

    filings_to_materialize = [
        filing for filing in filings if filing.available_at >= materialize_start
    ]

    for filing in filings_to_materialize:
        cached_chunks = await get_cached_sec_chunks(
            accession_number=filing.accession_number,
            chunking_version=SEC_CHUNKING_VERSION,
        )

        if cached_chunks:
            continue

        async with sec_chunk_lock(
            accession_number=filing.accession_number,
            chunking_version=SEC_CHUNKING_VERSION,
        ):
            cached_chunks = await get_cached_sec_chunks(
                accession_number=filing.accession_number,
                chunking_version=SEC_CHUNKING_VERSION,
            )

            if cached_chunks:
                continue

            document = await get_filing_document(
                filing=filing,
                user_agent=user_agent,
            )

            event = filing_to_market_event(
                filing,
                extract_filing_text(document),
            )

            chunks = chunk_sec_event(event)

            await upsert_evidence_chunks(
                chunks=chunks,
                chunking_version=SEC_CHUNKING_VERSION,
            )

    for filing in filings_to_materialize:
        chunks = await get_cached_sec_chunks(
            accession_number=filing.accession_number,
            chunking_version=SEC_CHUNKING_VERSION,
        )

        if not chunks:
            continue

        cached_embeddings = await get_cached_chunk_embeddings(
            chunk_ids=[chunk.chunk_id for chunk in chunks],
            embedding_model=EMBEDDING_MODEL_ID,
        )

        missing_chunks = [
            chunk for chunk in chunks if chunk.chunk_id not in cached_embeddings
        ]

        for chunk in missing_chunks:
            async with chunk_embedding_lock(
                chunk_id=chunk.chunk_id,
                embedding_model=EMBEDDING_MODEL_ID,
            ):
                existing = await get_cached_chunk_embeddings(
                    chunk_ids=[chunk.chunk_id],
                    embedding_model=EMBEDDING_MODEL_ID,
                )

                if existing:
                    continue

                embedding = embed_text(chunk.text)

                await upsert_chunk_embeddings(
                    chunk_ids=[chunk.chunk_id],
                    embeddings=[embedding],
                    embedding_model=EMBEDDING_MODEL_ID,
                )

    return filings


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


async def search_sec_filings(
    args: SearchSecFilingsArgs,
) -> list[EvidenceMatch]:
    unmaterialized_accessions = await get_unmaterialized_sec_accessions_between(
        symbol=args.symbol,
        start=args.start,
        end=args.end,
        chunking_version=SEC_CHUNKING_VERSION,
    )

    if unmaterialized_accessions:
        raise RuntimeError(
            "Requested SEC range is not fully materialized: "
            f"{len(unmaterialized_accessions)} filings are missing from local"
        )

    chunks = await get_cached_sec_chunks_between(
        symbol=args.symbol,
        start=args.start,
        end=args.end,
        chunking_version=SEC_CHUNKING_VERSION,
    )

    if not chunks:
        return []

    chunk_ids = [chunk.chunk_id for chunk in chunks]

    cached_embeddings = await get_cached_chunk_embeddings(
        chunk_ids=chunk_ids,
        embedding_model=EMBEDDING_MODEL_ID,
    )

    missing_chunk_ids = [
        chunk_id for chunk_id in chunk_ids if chunk_id not in cached_embeddings
    ]

    if missing_chunk_ids:
        raise RuntimeError(
            "SEC corpus is not fully prepared: "
            f"{len(missing_chunk_ids)} chunks are missing embeddings"
        )

    chunk_texts = [chunk.text for chunk in chunks]

    chunk_embeddings = np.array(
        [cached_embeddings[chunk.chunk_id] for chunk in chunks],
        dtype=np.float32,
    )

    hybrid_results = retrieve_chunks_hybrid(
        query=args.query,
        chunks=chunk_texts,
        chunk_embeddings=chunk_embeddings,
        top_k_per_method=10,
        top_k=10,
    )

    reranked_results = rerank_chunks(
        query=args.query,
        candidates=hybrid_results,
        reranker=load_reranker(),
        top_k=args.limit,
    )

    hybrid_by_index = {
        result.index: (rank, result)
        for rank, result in enumerate(
            hybrid_results,
            start=1,
        )
    }

    matches: list[EvidenceMatch] = []

    for reranker_rank, result in enumerate(
        reranked_results,
        start=1,
    ):
        hybrid_rank, hybrid_result = hybrid_by_index[result.index]

        matches.append(
            EvidenceMatch(
                chunk=chunks[result.index],
                tfidf_rank=hybrid_result.tfidf_rank,
                semantic_rank=hybrid_result.semantic_rank,
                hybrid_rank=hybrid_rank,
                rrf_score=hybrid_result.score,
                reranker_rank=reranker_rank,
                reranker_score=result.score,
            )
        )

    return matches
