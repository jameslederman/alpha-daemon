# AlphaDaemon TODO

## v0.1 deployment

- Provision hosted PostgreSQL with pgvector.
- Verify storage initialization and SEC retrieval against the hosted database.
- Run the API and worker locally against the hosted database.
- Exercise the asynchronous research API end to end:
  - `POST /research`
  - `GET /research/{workflow_id}`
- Start the Temporal Cloud trial only after the local hosted-database integration
  test passes.
- Configure the API and worker with the Temporal Cloud address, namespace, and
  API key.
- Deploy the worker container.
- Deploy the API container.
- Run a production smoke test through the public API.

## Near-term product work after deployment

- Add a minimal web UI for starting research and polling workflow status.
- Persist orchestrated query/task/synthesis results.
- Attach explicit evidence/provenance references to conclusions.
- Add research-usage accounting:
  - unique symbols investigated
  - tool calls
  - LLM calls
  - research rounds
  - elapsed time
  - estimated token/cost usage
- Add soft warnings and hard research-budget limits only after observing real
  usage patterns.

## Later

- Add macroeconomic research.
- Add portfolio-aware research and risk.
- Add longitudinal belief state and research-delta detection.
- Add knowledge-graph support.
- Add deterministic valuation and scenario analysis.
