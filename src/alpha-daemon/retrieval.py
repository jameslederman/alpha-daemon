from dataclasses import dataclass
import re
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from models import EvidenceChunk, MarketEvent


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
                f"section-{section_index}:"
                f"chunk-{chunk_index}"
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


@dataclass(frozen=True)
class RankedChunk:
    index: int
    text: str
    score: float


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

SEC_SECTION_PATTERN = re.compile(
    r"^(?:"
    r"PART\s+[IVX]+"
    r"|"
    r"ITEM\s+\d+[A-Z]?(?:\.\d+)?\.?(?:\s+.*)?"
    r")$",
    re.IGNORECASE,
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


@dataclass(frozen=True)
class DocumentSection:
    heading: str
    text: str


BARE_ITEM_PATTERN = re.compile(
    r"^ITEM\s+\d+[A-Z]?\.?$",
    re.IGNORECASE,
)


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