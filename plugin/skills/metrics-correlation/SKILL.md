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
- Preserve `files[].matches` as report `entityMatches` when present. Add the
  owning file's `path` (newPath, or oldPath for a deletion), `oldPath` and `newPath`;
  retain each match's `key`, `status`, `before[]` and `after[]` unchanged. Source
  ranges/signatures in before belong to oldPath/baseSha; after belongs to
  newPath/headSha. Use these groups for final `coverage.entityUnit: MATCH_GROUP`.
  Do not count two signatures in one `MATCHED` group as two changed entities.
  Frozen Independent Review uses `SNAPSHOT_ENTITY` source occurrences and may
  have a different count; preserve its original count and findings.
- `COMPARED` permits a delta only when both sides are `AVAILABLE` and their full
  definitions match. `INCOMPATIBLE` and `UNAVAILABLE` have no usable delta.
  `COMPARED` also requires Core's reliable entity identity: an `UNVERIFIED` group
  can carry two raw `AVAILABLE` values but its comparison remains `UNAVAILABLE`
  with null delta. Preserve `matchingWarning`; never reconstruct the withheld
  delta or claim an `UNVERIFIED` diagnostic is an established change.
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
- Copy each supplied `files[].coverage` into `fileCoverage`, adding only owning
  `path`, `oldPath`, `newPath`. Preserve its `base`/`head` statuses, line ranges and
  reasons exactly. Any `UNKNOWN` or `OUTSIDE_SUPPORTED_ENTITIES` needs a skip and
  `INCOMPLETE` under the current metric policy; an empty metric list does not
  establish coverage of fields, imports or initializers.

## Correlate without replacing the source review

1. Locate rows using Core's supplied matches and the correct file/version/range.
   A Python parameter change may retain a qualified-name match and a real delta;
   do not split it merely because before/after signatures differ. Conversely,
   function/owner renames, moves and ambiguous declarations need not have a pair.
   Do not infer a mapping or calculate a replacement delta. For a legacy response
   without matches, label that metadata unavailable and rely on the comparisons
   actually returned. Distinct reported path/entity keys use coverage unit
   `LEGACY_METRIC_ENTITY`, not `MATCH_GROUP`; leave unestablished total coverage
   unknown instead of inventing source pairs. Preserve
   independent findings unchanged in their frozen artifact; produce a separate
   final findings array.
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

Determine metric completeness from the measured response. The integrated Python
adapter supplies six metrics when its pinned cognitive dependency is available;
CogC failure must not erase five successful measurements. Neither a historical
`UNSUPPORTED` result nor missing metrics for unselected Java files justifies
forcing a complete Python-only review to `INCOMPLETE`.
