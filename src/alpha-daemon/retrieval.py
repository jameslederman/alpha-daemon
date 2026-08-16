from functools import cache
import boto3
from dataclasses import dataclass
import json
import numpy as np
import re
from sentence_transformers import CrossEncoder
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from models import EvidenceChunk, MarketEvent


BARE_ITEM_PATTERN = re.compile(
    r"^ITEM\s+\d+[A-Z]?\.?$",
    re.IGNORECASE,
)

SEC_SECTION_PATTERN = re.compile(
    r"^(?:"
    r"PART\s+[IVX]+"
    r"|"
    r"ITEM\s+\d+[A-Z]?(?:\.\d+)?\.?(?:\s+.*)?"
    r")$",
    re.IGNORECASE,
)

RERANKER_MODEL_ID = "cross-encoder/ms-marco-MiniLM-L6-v2"


@dataclass(frozen=True)
class RankedChunk:
    index: int
    text: str
    score: float


@dataclass(frozen=True)
class HybridRankedChunk:
    index: int
    text: str
    score: float
    tfidf_rank: int | None
    semantic_rank: int | None


@dataclass(frozen=True)
class DocumentSection:
    heading: str
    text: str


@dataclass(frozen=True)
class RerankedChunk:
    index: int
    text: str
    score: float


def chunk_text(
    text: str,
    max_chars: int = 4_000,
) -> list[str]:
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")

    paragraphs = [
        paragraph.strip()
        for paragraph in text.splitlines()
        if paragraph.strip()
    ]

    chunks: list[str] = []
    current_paragraphs: list[str] = []
    current_length = 0

    for paragraph in paragraphs:
        added_length = len(paragraph)

        if current_paragraphs:
            added_length += 1

        if current_length + added_length <= max_chars:
            current_paragraphs.append(paragraph)
            current_length += added_length
            continue

        if current_paragraphs:
            chunks.append("\n".join(current_paragraphs))
            current_paragraphs = []
            current_length = 0

        # Handle an unusually long paragraph.
        while len(paragraph) > max_chars:
            chunks.append(paragraph[:max_chars])
            paragraph = paragraph[max_chars:]

        if paragraph:
            current_paragraphs.append(paragraph)
            current_length = len(paragraph)

    if current_paragraphs:
        chunks.append("\n".join(current_paragraphs))

    return chunks

def chunk_sec_event(
    event: MarketEvent,
    max_chars: int = 4_000,
) -> list[EvidenceChunk]:
    if event.source is None:
        raise ValueError("event source is required")

    if event.source_id is None:
        raise ValueError("event source_id is required")

    sections = split_sec_sections(event.body)
    evidence_chunks: list[EvidenceChunk] = []

    for section_index, section in enumerate(sections):
        section_chunks = chunk_text(
            section.text,
            max_chars=max_chars,
        )

        for chunk_index, text in enumerate(
            section_chunks
        ):
            chunk_id = (
                f"{event.source}:"
                f"{event.source_id}:"
                f"section:{section_index}:"
                f"chunk:{chunk_index}"
            )

            evidence_chunks.append(
                EvidenceChunk(
                    chunk_id=chunk_id,
                    symbol=event.symbol,
                    source=event.source,
                    source_id=event.source_id,
                    source_url=event.source_url,
                    published_at=event.published_at,
                    section=section.heading,
                    chunk_index=chunk_index,
                    text=(
                        f"Section: {section.heading}\n\n"
                        f"{text}"
                    ),
                )
            )

    return evidence_chunks


def retrieve_chunks(
    query: str,
    chunks: list[str],
    top_k: int = 3,
) -> list[RankedChunk]:
    if not query.strip():
        raise ValueError("query must not be empty")

    if not chunks:
        return []

    if top_k <= 0:
        raise ValueError("top_k must be positive")

    vectorizer = TfidfVectorizer(
        stop_words="english",
        ngram_range=(1, 2),
    )

    matrix = vectorizer.fit_transform(
        [query, *chunks]
    )

    scores = cosine_similarity(
        matrix[0:1],
        matrix[1:],
    ).ravel()

    ranked_indices = scores.argsort()[::-1][:top_k]

    return [
        RankedChunk(
            index=int(index),
            text=chunks[index],
            score=float(scores[index]),
        )
        for index in ranked_indices
    ]


def retrieve_for_queries(
    queries: list[str],
    chunks: list[str],
    top_k_per_query: int = 2,
) -> list[RankedChunk]:
    if top_k_per_query <= 0:
        raise ValueError(
            "top_k_per_query must be positive"
        )

    selected: dict[int, RankedChunk] = {}

    for query in queries:
        results = retrieve_chunks(
            query=query,
            chunks=chunks,
            top_k=top_k_per_query,
        )

        for result in results:
            existing = selected.get(result.index)

            if (
                existing is None
                or result.score > existing.score
            ):
                selected[result.index] = result

    # Present evidence in its original document order.
    return sorted(
        selected.values(),
        key=lambda result: result.index,
    )


def find_sec_section_headings(
    text: str,
) -> list[tuple[int, str]]:
    headings: list[tuple[int, str]] = []

    for line_number, raw_line in enumerate(
        text.splitlines()
    ):
        line = " ".join(raw_line.split())

        if (
            line
            and len(line) <= 200
            and SEC_SECTION_PATTERN.fullmatch(line)
        ):
            headings.append(
                (line_number, line)
            )

    return headings


def split_sec_sections(
    text: str,
) -> list[DocumentSection]:
    lines = text.splitlines()

    headings = [
        (line_number, heading)
        for line_number, heading
        in find_sec_section_headings(text)
        if heading.upper().startswith("ITEM ")
        and not BARE_ITEM_PATTERN.fullmatch(heading)
    ]

    sections: list[DocumentSection] = []

    for position, (line_number, heading) in enumerate(
        headings
    ):
        next_line_number = (
            headings[position + 1][0]
            if position + 1 < len(headings)
            else len(lines)
        )

        section_text = "\n".join(
            lines[line_number + 1 : next_line_number]
        ).strip()

        if section_text:
            sections.append(
                DocumentSection(
                    heading=heading,
                    text=section_text,
                )
            )

    return sections

@cache
def get_bedrock_runtime():
    return boto3.client(
        "bedrock-runtime",
        region_name="us-east-1",
    )

def embed_text(
    text: str,
    model_id: str = "amazon.titan-embed-text-v2:0",
) -> list[float]:
    client = get_bedrock_runtime()

    response = client.invoke_model(
        modelId=model_id,
        body=json.dumps(
            {
                "inputText": text,
                "dimensions": 512,
                "normalize": True,
            }
        ),
    )

    body = json.loads(response["body"].read())

    return body["embedding"]


def embed_chunks(
    chunks: list[str],
) -> np.ndarray:
    return np.array(
        [
            embed_text(chunk)
            for chunk in chunks
        ],
        dtype=np.float32,
    )


def retrieve_chunks_semantic(
    query: str,
    chunks: list[str],
    chunk_embeddings: np.ndarray,
    top_k: int = 3,
) -> list[RankedChunk]:
    if not query.strip():
        raise ValueError("query must not be empty")

    if not chunks:
        return []

    if top_k <= 0:
        raise ValueError("top_k must be positive")

    if len(chunks) != len(chunk_embeddings):
        raise ValueError(
            "chunks and chunk_embeddings must have "
            "the same length"
        )

    query_embedding = np.array(
        embed_text(query),
        dtype=np.float32,
    )

    scores = chunk_embeddings @ query_embedding

    ranked_indices = scores.argsort()[::-1][:top_k]

    return [
        RankedChunk(
            index=int(index),
            text=chunks[index],
            score=float(scores[index]),
        )
        for index in ranked_indices
    ]


def retrieve_chunks_hybrid(
    query: str,
    chunks: list[str],
    chunk_embeddings: np.ndarray,
    top_k_per_method: int = 5,
    top_k: int = 5,
    rrf_k: int = 60,
) -> list[HybridRankedChunk]:
    tfidf_results = retrieve_chunks(
        query=query,
        chunks=chunks,
        top_k=top_k_per_method,
    )

    semantic_results = retrieve_chunks_semantic(
        query=query,
        chunks=chunks,
        chunk_embeddings=chunk_embeddings,
        top_k=top_k_per_method,
    )

    tfidf_ranks = {
        result.index: rank
        for rank, result in enumerate(
            tfidf_results,
            start=1,
        )
    }

    semantic_ranks = {
        result.index: rank
        for rank, result in enumerate(
            semantic_results,
            start=1,
        )
    }

    candidate_indices = (
        set(tfidf_ranks)
        | set(semantic_ranks)
    )

    results: list[HybridRankedChunk] = []

    for index in candidate_indices:
        tfidf_rank = tfidf_ranks.get(index)
        semantic_rank = semantic_ranks.get(index)

        score = 0.0

        if tfidf_rank is not None:
            score += 1 / (rrf_k + tfidf_rank)

        if semantic_rank is not None:
            score += 1 / (rrf_k + semantic_rank)

        results.append(
            HybridRankedChunk(
                index=index,
                text=chunks[index],
                score=score,
                tfidf_rank=tfidf_rank,
                semantic_rank=semantic_rank,
            )
        )

    return sorted(
        results,
        key=lambda result: result.score,
        reverse=True,
    )[:top_k]

@cache
def load_reranker() -> CrossEncoder:
    return CrossEncoder(RERANKER_MODEL_ID)

def rerank_chunks(
    query: str,
    candidates: list[HybridRankedChunk],
    reranker: CrossEncoder,
    top_k: int = 3,
) -> list[RerankedChunk]:
    if not candidates:
        return []

    documents = [
        candidate.text
        for candidate in candidates
    ]

    rankings = reranker.rank(
        query,
        documents,
        top_k=top_k,
    )

    return [
        RerankedChunk(
            index=candidates[
                int(result["corpus_id"])
            ].index,
            text=candidates[
                int(result["corpus_id"])
            ].text,
            score=float(result["score"]),
        )
        for result in rankings
    ]