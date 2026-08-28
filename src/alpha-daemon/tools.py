from edgar import get_filing_events_between
from market_data import MarketDataProvider
from models import (
    EvidenceMatch,
    GetPriceHistoryArgs,
    MarketBar,
    NewsArticle,
    SearchCompanyNewsArgs,
    SearchSecFilingsArgs,
)
from retrieval import (
    chunk_sec_event,
    embed_chunks,
    load_reranker,
    rerank_chunks,
    retrieve_chunks_hybrid,
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


async def search_sec_filings(
    args: SearchSecFilingsArgs,
    user_agent: str,
) -> list[EvidenceMatch]:
    events = await get_filing_events_between(
        symbol=args.symbol,
        user_agent=user_agent,
        start=args.start,
        end=args.end,
    )

    chunks = [chunk for event in events for chunk in chunk_sec_event(event)]

    if not chunks:
        return []

    chunk_texts = [chunk.text for chunk in chunks]
    chunk_embeddings = embed_chunks(chunk_texts)

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
        for rank, result in enumerate(hybrid_results, start=1)
    }

    matches = []

    for reranker_rank, result in enumerate(reranked_results, start=1):
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
