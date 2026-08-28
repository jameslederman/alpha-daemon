# AlphaDaemon

AlphaDaemon is an experimental, evidence-grounded financial research system. It
uses durable Temporal workflows to plan research, retrieve point-in-time
evidence, answer scoped questions in parallel, and synthesize an auditable
investment recommendation.

The current prototype includes:

- SEC EDGAR filing ingestion and section-aware chunking
- TF-IDF and semantic retrieval with reciprocal-rank fusion and reranking
- Bedrock-based research planning and evidence-constrained synthesis
- A Strands fundamental analyst with price, news, and SEC search tools
- Persistent, content-addressed artifact caching

## Persistent artifacts

Raw provider responses are stored beneath `.alpha-daemon/` by default. SQLite
records provenance and freshness metadata; payloads are deduplicated by SHA-256
in a content-addressed blob directory.

EDGAR uses source-specific freshness policies:

- Filing documents are immutable and cached indefinitely.
- The SEC ticker index is refreshed after 24 hours.
- Company submissions are refreshed after 30 minutes.
- Failed HTTP responses are never cached.

Set `ALPHA_DAEMON_DATA_DIR` to put the artifact store elsewhere. Repeating an
identical filing search reuses eligible persisted responses instead of calling
EDGAR again.

## Status

AlphaDaemon is research software under active development. See [ROADMAP.md](ROADMAP.md)
for release scope and exit criteria.

This project is not financial advice and is not ready for live trading.

