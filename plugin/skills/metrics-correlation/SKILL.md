---
name: metrics-correlation
description: Correlate a frozen CodeClarity independent review with measured Java/Python metrics, preserving unavailable values and algorithm compatibility while producing evidence-backed final findings.
---

# Correlate measured metrics and findings

Require a frozen Independent Review artifact and raw MCP/Core analysis results for
the same selected scope and SHAs. Use the
[review contract](../../contracts/review.schema.json) and
[MCP compatibility guide](../../contracts/mcp-compatibility.md). If the independent
stage is absent or ran after current measurements, retain the static results but
mark the required stage incomplete; do not recreate an allegedly independent review.

## Preserve the measurements

For each selected changed entity present these six metric IDs:

| ID | Purpose | Initial contextual signal |
|---|---|---|
| `cyclomatic_complexity` | Execution branches under its declared algorithm | At least 10 |
| `cognitive_complexity` | Difficulty of following control flow | At least 15 |
| `function_sloc` | Function source lines under its declared definition | More than 60 |
| `max_nesting_depth` | Nesting under the adapter's definition | More than 4 |
| `parameter_count` | Formal parameters under the adapter's definition | More than 5 |
| `return_count` | Explicit returns under the adapter's definition | Informational; no automatic threshold |

These are starting heuristics, not universal quality rules. A configured policy,
when supplied by Core, takes precedence; retain its identity in the report.

- All numbers, including a displayed delta, come from MCP/Core. Do not estimate
  missing metrics, parse diagnostic prose to invent values, count them as a model,
  or recompute a missing delta. Preserve the analyzer/algorithm definitions and
  the raw comparison status. Definitions from different languages are not
  equivalent just because the metric IDs match.
- The current representation is `files[].metrics[]` containing `entity`, `metric`,
  `status`, `before`, `after`, and `delta`; each side has `definition`, `status`,
  `value`, and `reason`. Attach the correct repository path when flattening rows.
  `definition.analyzer` includes the analyzer version; `definition.algorithm`
  identifies semantics. A future schema must be read from discovery/contracts.
- `COMPARED` permits a delta only when both sides are `AVAILABLE` and their full
  definitions match. `INCOMPATIBLE` and `UNAVAILABLE` have no usable delta.
  Preserve `UNSUPPORTED`, `MISSING`, `ERROR`, and `ENTITY_ABSENT`; display no
  number for these states. `ENTITY_ABSENT` is legitimate for additions/deletions
  and must not become zero or an automatic completeness failure by itself.
- If a required metric is absent from the response, retain its absence from JSON
  `metrics[]` and add a `skips` reason identifying the entity and metric ID. Display
  `MISSING` cells in the six-metric Markdown table; the report helper renders these
  cells without manufacturing a comparison or analyzer definition. Preserve an
  explicit analyzer-returned `MISSING` measurement as received. Missing mandatory
  metrics, partial files, missing batches, or unprocessed entities require
  `INCOMPLETE`, even when the prototype's top-level status is `ok`.

## Correlate without replacing the source review

1. Match rows to the correct file, entity, version and finding location. Check added,
   deleted and unmatched signatures explicitly; a rename/signature change need not
   have a reliable before/after pair. Preserve independent findings unchanged in
   their frozen artifact; produce a separate final findings array.
2. Assign each final finding one relation:
   - `SUPPORTED`: a relevant measured value/change and verified source context
     support this same observation; reference the actual rows.
   - `UNRELATED`: the concern does not depend on these measurements, as is common
     for unclear naming or unnecessary abstraction.
   - `INSUFFICIENT_DATA`: the needed values/context are unavailable or incompatible.
   Do not reject Naming/Abstraction because CC/CogC is low. An apparent contradiction
   should be explained with evidence and may warrant revisiting the observation;
   it is not an automatic rejection or developer feedback.
3. Inspect contextual signals from metrics and rule diagnostics. Exceeding a
   threshold or increasing a value is a prompt for contextual review, not proof of
   poor readability. Add `source: METRIC_SIGNAL` only with the observed metric and
   source evidence, a precise location/snapshot, and a useful recommendation.
   Do not create a return-count defect solely from its number.
4. Merge duplicate observations at the same location/category, retain evidence from
   each source, and keep distinct issues separate. Canonicalize categories against
   known history categories during final report assembly when available. If a
   category/location/evidence changes, remove the old `findingId` and regenerate
   the final ID with the bundled
   [review_ids.py](../readability-review/scripts/review_ids.py). Set
   `originFindingIds` to every frozen finding ID the canonicalized/merged observation
   supersedes, and preserve all their source observations and evidence. A relation-only
   change retains the original ID. The frozen independent findings remain byte-equivalent
   to the retained artifact; never mutate them after measurement.

Return normalized metric rows, final findings, analyzer definitions, coverage and
skips to the orchestrator. If required processing failed, return the available
results and the exact missing work. Optional LSP failure alone does not invalidate
valid AST/metrics. No history writes, human feedback, source edits, or rule activation
belong to this stage.
