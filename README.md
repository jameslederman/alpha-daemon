# AlphaDaemon

**Durable, evidence-backed AI research infrastructure for point-in-time public-market analysis.**

AlphaDaemon is an experimental agentic market-intelligence system designed to research companies, retrieve and rank primary-source evidence, preserve point-in-time state, and ultimately turn that evidence into auditable forecasts and investment decisions.

The project is intentionally built as more than an LLM wrapper. Its core engineering focus is on the hard parts of production-grade AI systems: **durable orchestration, data provenance, retrieval quality, persistent memory, point-in-time correctness, tool boundaries, caching, and deterministic/agentic separation of concerns.**

> **Current focus:** skill-scoped public-company research with SEC-backed fundamental analysis, a persistent local evidence corpus, and Temporal-orchestrated planning, child workflows, and synthesis.

---

## Why AlphaDaemon Exists

Most “AI stock research” demos follow a simple pattern:

```text
prompt → LLM → web search → answer
```

AlphaDaemon is being built around a different model:

```text
ResearchRun
    ↓
deterministic corpus preparation
    ↓
persistent, point-in-time evidence
    ↓
agent-directed research
    ↓
hybrid retrieval + reranking
    ↓
structured findings
    ↓
forecast assumptions
    ↓
deterministic valuation
    ↓
recommendation
```

The long-term goal is an **always-on, event-driven market intelligence system that maintains evidence-backed, point-in-time research state across companies and time**.

That means AlphaDaemon should eventually be able to answer not only:

> “What do we think about AAPL today?”

but also:

> “What did the system believe about AAPL six months ago, what evidence supported that belief, and what changed?”

That longitudinal machine-belief history is a central design goal.

---

## Current Architecture

```text
ResearchQuery
    ↓
ResearchPlanner
    ↓
bounded ResearchPlan
    ↓
Temporal validates and executes the plan
    ↓
ResearchTaskWorkflow child workflows
    ↓
ResearchAgent + registered ResearchSkill
    ↓
bounded domain tools
    ↓
typed specialist results
    ↓
ResearchSynthesizer
    ↓
ResearchSynthesis
```

The planner can choose only registered skills. It does not create executable workflow
code or choose arbitrary tools. Research agents may expand across relevant securities,
while infrastructure clamps point-in-time tool boundaries to each task's `as_of`.
Temporal owns execution of the validated plan.

The existing `FundamentalAnalysisWorkflow` remains as a built-in entry point. It
prepares the SEC working corpus and then invokes the same generic
`ResearchAgent` with the `fundamental_analysis` skill.

The system separates **what the agent should decide** from **what infrastructure must guarantee**.

### Infrastructure owns

- point-in-time boundaries
- source provenance
- data synchronization
- durable execution
- caching and persistence
- chunking and embedding versions
- retrieval mechanics
- failure/retry semantics

### Agents own

- what research questions to ask
- which evidence to inspect
- how to synthesize findings
- when deeper investigation is warranted

This separation keeps the system agentic without making correctness depend on unconstrained LLM behavior.

---

## Implemented So Far

### Durable agent orchestration with Temporal

AlphaDaemon uses **Temporal** to make agent workflows durable and observable.

The current research runtime supports two execution paths:

1. a direct `ResearchTaskWorkflow` for a specific registered skill and objective
2. a `ResearchOrchestratorWorkflow` that plans a query, launches bounded child
   research workflows, gathers their typed results, and synthesizes a final answer

The built-in `FundamentalAnalysisWorkflow` remains available for the standard
company-fundamentals path and uses the same generic research runtime underneath.

Temporal provides durable retries, activity isolation, child-workflow execution,
workflow state, and a clean path toward long-running autonomous research processes.

---

### Strands agent integration

The generic `ResearchAgent`, research planner, and synthesizer are implemented with
**Strands Agents** and executed through Temporal.

The model currently uses Amazon Nova Pro through AWS Bedrock.

Each research skill declares its instructions, structured output type, and allowed
tool set. Agent tools are explicit and bounded. Domain capabilities remain separate
from orchestration wrappers:

```text
Domain capability
        │
   ┌────┴────┐
Temporal   Agent tool
activity   schema
```

This avoids coupling business logic directly to either Temporal or a particular agent framework.

---

### Persistent SEC filing inventory

AlphaDaemon maintains a local inventory of SEC filings rather than rediscovering the same corpus for every agent question.

For a company research run, the system currently:

```text
SEC metadata refresh
        ↓
~10 years of filing inventory
        ↓
persist metadata in Postgres
        ↓
materialize recent working corpus
```

For AAPL, the current implementation discovers roughly ten years of 10-K, 10-Q, and 8-K metadata and persists the inventory locally.

This creates an important distinction:

```text
sec_filing_inventory
    "SEC says this filing exists"

sec_filings
    "we have downloaded and stored this filing"
```

The system can therefore know that historical evidence exists without eagerly downloading and embedding every filing.

---

### Persistent evidence corpus

The default working corpus materializes the most recent filing history into durable local storage:

```text
SEC filing
    ↓
raw HTML
    ↓
cleaned text
    ↓
section-aware chunks
    ↓
persistent chunk records
    ↓
persistent vector embeddings
```

Storage currently uses:

- PostgreSQL 17
- pgvector
- versioned chunk IDs
- persistent raw filing HTML
- cleaned filing text
- persistent evidence chunks
- persistent embeddings

The cache is designed so repeated research runs do not redownload, rechunk, or re-embed unchanged evidence.

---

### Concurrency-safe corpus preparation

Agentic workflows can generate multiple tool calls concurrently. Without coordination, several workers could independently discover the same cache miss and duplicate expensive work.

AlphaDaemon uses PostgreSQL advisory locks to protect cold-cache operations such as:

- SEC filing retrieval
- chunk generation
- embedding generation

The general pattern is:

```text
check cache
    ↓
miss
    ↓
acquire advisory lock
    ↓
check cache again
    ↓
perform expensive work only if still missing
```

This allows multiple Temporal activities or workers to share the same persistent corpus safely.

---

## Retrieval Pipeline

SEC research uses a multi-stage hybrid retrieval pipeline:

```text
research question
      ↓
TF-IDF retrieval
      +
semantic retrieval
      ↓
Reciprocal Rank Fusion
      ↓
cross-encoder reranker
      ↓
EvidenceMatch[]
```

### Lexical retrieval

TF-IDF provides strong exact-term and domain-language matching.

### Semantic retrieval

Chunks are embedded with:

```text
amazon.titan-embed-text-v2:0
512 dimensions
normalized embeddings
```

Embeddings are persisted in PostgreSQL using pgvector.

### Hybrid ranking

Lexical and semantic rankings are combined using **Reciprocal Rank Fusion (RRF)**.

### Cross-encoder reranking

The fused candidate set is reranked using:

```text
cross-encoder/ms-marco-MiniLM-L6-v2
```

This gives the system a relatively inexpensive first-stage search followed by a stronger relevance model over a small candidate set.

---

## Point-in-Time Research

Point-in-time correctness is a first-class concern.

Every `ResearchRun`, `ResearchQuery`, and `ResearchTask` carries an exact
timezone-aware `as_of` timestamp.

SEC filing eligibility is based on the filing's actual availability timestamp, not simply its reporting period.

Conceptually:

```text
filing existed before the active as_of boundary?
        ↓
yes → eligible
no  → invisible to the run
```

This is essential for historical backtesting and prevents future information from leaking into past research states.

The architecture is being designed so that this same point-in-time boundary can eventually apply across:

- SEC filings
- market data
- news
- macroeconomic releases
- forecasts
- recommendations

---

## Research Data Model

The research architecture is organized around structured objects rather than
unconstrained agent spawning.

The new skill-oriented orchestration path is:

```text
ResearchQuery
→ ResearchPlan
→ ResearchTask[]
→ ResearchTaskResult[]
→ ResearchSynthesis
```

The earlier evidence/recommendation path remains in the codebase:

```text
ResearchRun
→ ResearchQuestion[]
→ QuestionEvidence[]
→ ResearchFinding[]
→ Recommendation
```

Current models include:

- `ResearchRun`
- `ResearchScope`
- `ResearchQuery`
- `ResearchPlan`
- `ResearchTask`
- `ResearchTaskResult`
- `ResearchSynthesis`
- `ResearchQuestion`
- `EvidenceChunk`
- `EvidenceMatch`
- `QuestionEvidence`
- `ResearchFinding`
- `FundamentalAnalysis`
- `Recommendation`
- `Filing`

The goal is for every higher-level conclusion to remain traceable back to the evidence that produced it.

---

## Example Fundamental Research Flow

For an AAPL analysis through the orchestrator:

```text
ResearchQuery(AAPL, objective, as_of)
        ↓
ResearchPlanner selects fundamental_analysis
        ↓
ResearchTaskWorkflow child
        ↓
ResearchAgent + fundamental_analysis skill
        ↓
SEC / company-news / price capabilities
        ↓
hybrid SEC retrieval + reranking
        ↓
structured FundamentalAnalysis
        ↓
ResearchSynthesizer
        ↓
ResearchSynthesis
```

The direct built-in `FundamentalAnalysisWorkflow` also refreshes the ten-year SEC
metadata inventory and prewarms the recent working corpus before invoking the same
generic agent runtime. Wider historical SEC ranges can be materialized on demand.

Once the corpus is warm, the agent can issue several SEC searches without repeatedly
downloading unchanged filings or recomputing document embeddings.

---

## Technology Stack

### AI / Agents

- AWS Bedrock
- Amazon Nova Pro
- Amazon Titan Text Embeddings v2
- Strands Agents
- Hugging Face / Sentence Transformers
- CrossEncoder reranking

### Orchestration

- Temporal
- Temporal Python SDK
- Temporal + Strands integration

### Retrieval

- TF-IDF
- semantic embeddings
- Reciprocal Rank Fusion
- cross-encoder reranking
- section-aware SEC chunking

### Storage

- PostgreSQL 17
- pgvector
- psycopg 3
- PostgreSQL advisory locks

### Data / Providers

- SEC EDGAR
- Massive market data integration
- provider-neutral market-data interfaces

### Core Python

- Python 3.14
- Pydantic
- NumPy
- scikit-learn
- httpx
- BeautifulSoup
- Ruff
- Pyright

---

## Design Principles

### 1. Domain capabilities first

Core capabilities should not depend on Temporal, Strands, or any particular LLM provider.

```text
LLM chooses capability
        ↓
Temporal / agent wrapper
        ↓
domain capability
        ↓
service/provider interface
        ↓
SEC | Massive | FRED | ...
```

### 2. Deterministic infrastructure, agentic investigation

The agent can choose what to investigate.

It should not control critical correctness policies such as:

- `as_of`
- source eligibility
- cache semantics
- persistence
- retries
- provenance

### 3. Evidence before conclusions

Recommendations should ultimately be reconstructable from:

```text
recommendation
    ↓
findings
    ↓
evidence
    ↓
source document
```

### 4. Persistent memory over ephemeral context

LLM context windows are not treated as long-term memory.

AlphaDaemon's long-term memory is intended to have several layers:

```text
Research / belief memory
    findings, forecasts, confidence, recommendations
            ↑
Evidence memory
    chunks, embeddings, provenance
            ↑
Source archive
    raw filings, metadata, market/news data
```

### 5. Version derived artifacts

Chunks and embeddings are treated as derived data with explicit identities so future changes in chunking or embedding strategy do not silently corrupt retrieval behavior.

---

## Current Status

The project is under active development.

Working today:

- Temporal workflow execution
- Strands / Bedrock analyst agent
- SEC 10-K / 10-Q / 8-K discovery
- historical SEC submissions inventory
- ~10-year metadata synchronization
- point-in-time filing filtering
- persistent SEC document storage
- section-aware chunking
- persistent chunk storage
- Titan embedding persistence
- pgvector integration
- concurrency-safe cache population
- TF-IDF retrieval
- semantic retrieval
- RRF hybrid search
- cross-encoder reranking
- agent-accessible SEC research
- structured fundamental-analysis output

---

## Roadmap

### Near term

- materialize older SEC filings on demand when the agent needs evidence outside the default working corpus
- persist research findings and recommendations
- attach explicit evidence IDs to analyst conclusions
- add deterministic valuation models
- add macroeconomic research
- improve connection pooling and storage abstractions
- move vector similarity search fully into PostgreSQL where appropriate
- add tests around point-in-time guarantees and cache completeness

### Medium term

- persistent longitudinal belief state
- event-driven research refreshes
- knowledge-graph layer
- portfolio-aware research
- scenario / bear-base-bull forecasting
- richer market and news evidence
- research-delta detection: “what changed since the previous run?”

### Product layer

A future web interface is intended to expose:

- live Temporal workflow state
- agent research traces
- evidence provenance
- historical recommendations
- belief changes through time
- conversational Q&A over research state

---

## Running Locally

AlphaDaemon currently assumes a local development environment with:

- Python 3.14
- PostgreSQL 17
- pgvector
- Temporal development server
- AWS Bedrock credentials
- SEC user-agent configuration

Environment variables currently include:

```bash
DATABASE_URL=postgresql://localhost/alpha_daemon
SEC_USER_AGENT="Your Name your-email@example.com"
MASSIVE_API_KEY="..."
```

AWS credentials should be configured through the normal AWS credentials/profile mechanism rather than committed to the repository.

Start Temporal:

```bash
temporal server start-dev
```

Start the worker:

```bash
PYTHONPATH=src/alpha-daemon python src/alpha-daemon/worker.py
```

---

## Engineering Themes Demonstrated

AlphaDaemon is also intentionally a portfolio project demonstrating practical AI/ML engineering beyond notebook-level modeling.

The project exercises:

- agent architecture
- durable distributed workflows
- async Python
- structured LLM outputs
- tool design
- retrieval-augmented generation
- hybrid information retrieval
- vector search
- model reranking
- persistence
- cache design
- distributed locking
- API integration
- point-in-time data engineering
- provenance and auditability
- provider abstraction
- failure handling
- system decomposition

The objective is not to create a thin financial chatbot. It is to build the infrastructure required for an AI research system whose conclusions can be **reproduced, inspected, challenged, and compared through time**.

---

## Disclaimer

AlphaDaemon is an experimental software and research project. It is not investment advice, and its outputs should not be treated as financial recommendations.
