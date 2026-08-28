# AlphaDaemon Roadmap

The current release is the only detailed work queue. Later releases capture
direction and will be decomposed when their prerequisites are complete.

## v0.1 — Reproducible research engine

Scope:

- [x] Durable Temporal research workflow
- [x] SEC EDGAR ingestion and evidence retrieval
- [x] Agent-driven price, news, and SEC research tools
- [x] Persistent artifact store and EDGAR request deduplication
- [ ] Persist complete research traces and model/configuration metadata
- [ ] Replace or supplement Massive with Alpaca market data and news
- [ ] Add revision-aware FRED/ALFRED macroeconomic data
- [ ] Normalize all provider access behind common snapshot interfaces
- [ ] Produce one public, reproducible multi-source research trace
- [ ] Document clean-environment setup and tag `v0.1.0`

Exit criteria:

- Repeated runs make no unnecessary external requests.
- Every published result records its data snapshot and evidence provenance.
- One end-to-end run combines company filings, macro data, prices, and news.
- Setup and the public demo run are reproducible from a clean environment.

## v0.2 — Knowledge graph

Add Neo4j entity resolution, evidence lineage, and multi-hop retrieval. Retain
the v0.1 demo as a baseline and measure relationship discovery, evidence
coverage, and unsupported-claim rate before and after graph retrieval.

## v0.3 — Persistent theses

Track claims, evidence, contradictions, confidence changes, and thesis history
so new information updates prior research rather than replacing it.

## v0.4 — Specialized research agents

Add analysts, critics, and governance only where controlled ablations show that
specialization improves research quality.

## v0.5 — Portfolio-aware paper trading

Add portfolio context and a proposal-to-approval-to-execution flow using Alpaca
paper trading. Keep deterministic position, exposure, and risk checks outside
the language model.

## v1.0 — Interactive research product

Add trace exploration and conversational access to current and historical
reasoning, including questions such as why a prior rating was issued or what
changed in a thesis.

## v1.1+ — Options

Add contract-aware analytics, Greeks, liquidity and expiry controls, nonlinear
portfolio risk, and paper execution before considering live orders.

