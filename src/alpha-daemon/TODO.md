# AlphaDaemon TODO

## SEC Retrieval

### Support searches beyond the materialized SEC corpus

The SEC inventory currently tracks ~10 years of filing metadata, while only the most recent ~2 years are materialized into documents, chunks, and embeddings.

If an agent requests a date range containing known but unmaterialized filings, `search_sec_filings()` detects the incomplete corpus.

Decide how to handle this case:

- Allow the agent to request expansion of the materialized corpus on demand.
- Or constrain agent searches to the currently materialized window.
- Preserve the `ResearchRun.as_of` boundary in either approach.

Preferred direction: lazy on-demand materialization of filings already present in `sec_filing_inventory`.