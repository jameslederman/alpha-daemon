# Fundamental Analysis

## Purpose

Assess the underlying operating and financial fundamentals of a public company using evidence gathered through the available research tools.

## Required research lenses

Investigate the areas most relevant to the objective, including:

- revenue and earnings trends
- margins and operating performance
- cash flow and balance sheet strength
- management guidance
- capital allocation
- material company-specific developments
- risks that could materially affect future fundamentals

The objective may emphasize only a subset of these lenses or may request a longer historical comparison. Use judgment to focus the research accordingly.

## Evidence rules

- Use available tools for factual claims about the company.
- Prefer primary-source SEC evidence when the question is addressed by company filings.
- Use company news and market data when they are relevant to the objective.
- Respect the task's point-in-time `as_of` boundary.
- Distinguish evidence from inference.
- If a retrieval tool reports incomplete corpus coverage, explicitly account for that limitation.
- Lower confidence when evidence is incomplete, stale, or conflicting.

## Boundaries

- Do not make a BUY, HOLD, or SELL recommendation.
- Do not perform valuation or set a price target.
- Do not invent facts absent from the available evidence.

## Output

Return a structured `FundamentalAnalysis` containing:

- `symbol`
- `summary`
- `strengths`
- `risks`
- `confidence`
