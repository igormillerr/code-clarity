---
name: readability-review
description: Review readability of committed Java and Python Git changes with CodeClarity, combining source-first AI review, measured metrics, an evidence-backed report, and optional rule discovery.
---

# CodeClarity readability review

Run one review for the user's repository and Git scope. Use the bundled
[review contract](../../contracts/review.schema.json) and
[MCP compatibility guide](../../contracts/mcp-compatibility.md). Supporting stages
are [independent-review](../independent-review/SKILL.md),
[metrics-correlation](../metrics-correlation/SKILL.md), and
[rule-discovery](../rule-discovery/SKILL.md). Load each when its stage begins.

## Establish the scope

1. Discover the tools exposed by the connected CodeClarity server and read their
   actual schemas. When advertised, use `get_changes(baseRef, headRef)`,
   `analyze_changes(baseSha, headSha, paths?)`, and
   `get_symbol_context(commitSha, path, line)`. They route Java/Python files
   automatically; no language or metric-selection argument is needed. Otherwise
   use the advertised `inspect_symbol_ast` for compact AST context and/or
   `list_java_changes`, `list_python_changes`, `analyze_java_changes`,
   `analyze_python_changes`, `inspect_java_method`, and `inspect_python_function`.
   Never invent a tool or argument. Missing MCP access is an explicit limitation.
2. Resolve the user's base/head through the change-list tool before reading code.
   The current server compares **merge-base(baseRef, headRef) to head** and only
   committed snapshots. Do not silently substitute worktree/staged/untracked code.
   If the requested base or mode is ambiguous, resolve that ambiguity before review.
3. Record `scope`: `repoRoot`, resolved `baseSha`, `headSha`, `snapshotId` (the head
   SHA for this commit-only mode), selected `languages`, and selected `paths`.
   Collect the complete selected change list for both languages and verify that all
   calls refer to the same snapshots. Record explicitly excluded/unsupported files.
   A selected path not returned by the tool must be reported, not silently dropped.
   Preserve listing `partial` status and warnings; empty ranges from a failed file
   do not establish that the file has no changed entities.
4. Obtain a deterministic `reviewId` with
   [scripts/review_ids.py](scripts/review_ids.py), passing JSON `{ "scope": ...,
   "findings": [] }` on stdin. Do not include timestamps in scope identity.

If every requested change-list operation succeeds and the selected diff is empty,
return `NO_CHANGES` with the resolved scope and empty findings/metrics. Do not run
analysis, fabricate findings, or propose a rule. A failed listing is not an empty
diff. If only unsupported files changed, explain the unsupported scope rather than
claiming a successful review of those files.

## Run the stages in order

1. **Independent Review.** Before calling any `analyze_*` tool, inspect the complete
   changed source/diff at the resolved SHAs and apply `independent-review`. Analysis
   responses include metrics and threshold findings, so they cannot be used to
   discover what to review during this stage. Use diff ranges and AST inspection
   instead. Store its status, coverage, findings, and omissions as an independent
   artifact; freeze that artifact before requesting the first metric. Preserve the
   artifact's path/content hash and the `independent_review_frozen` trace event.
   Its entity coverage unit is `SNAPSHOT_ENTITY`: count an affected source entity
   separately at base and head, so reviewing both versions of one function counts
   two occurrences. Do not call analysis to obtain matching groups before freeze.
   Subsequent correlation may extend final findings, but must not rewrite the
   frozen independent result. Separate Skills provide logical ordering in the same
   conversation; they do not guarantee isolated model contexts.
2. **Measured results.** Call the discovered analysis operation(s), using exactly
   the resolved SHAs and the selected files. Prefer one `analyze_changes` call for
   a mixed Java/Python batch; use the language-specific analysis tools as fallback.
   Batch at most 50 paths per call and retain every result/warning, including
   healthy file results from a `partial` response. Preserve raw tool results or
   trace references; retry only the failed batch, without replacing prior results.
   When `files[].matches` is returned, preserve every Core match under report
   `entityMatches`, adding only `path`, `oldPath`, and `newPath` from the owning
   file. Keep `key`, `status`, `before`, and `after` exactly as returned. Final
   entity coverage uses these logical groups (`entityUnit: MATCH_GROUP`), not a
   union of old/new signature strings. It can differ from frozen source coverage.
   Read numerical measurements from `files[].metrics[]`, including entities with
   no threshold findings. For every touched entity check all six metric IDs:
   `cyclomatic_complexity`, `cognitive_complexity`, `function_sloc`,
   `max_nesting_depth`, `parameter_count`, and `return_count`.
   One analysis call returns all implemented metrics; no separate calls per metric
   are needed. Preserve each measurement's `before`, `after`, `delta`, comparison
   status, and both analyzer/algorithm definitions. Do not substitute `findings`
   for numerical measurements or calculate missing values yourself.
   Preserve `files[].coverage` under report `fileCoverage`, adding only the
   owning `path`, `oldPath` and `newPath`. Keep its `base`/`head` sides unchanged.
   `OUTSIDE_SUPPORTED_ENTITIES` or `UNKNOWN` is an explicit coverage limitation:
   retain the path/ranges/reason in `skips` and use `INCOMPLETE` under the current
   entity-metric policy, including field-only changes with no metric rows.
3. **Correlation.** Apply `metrics-correlation` to the frozen independent artifact
   and measured results. Deduplicate observations about the same issue/location,
   retaining their evidence. A static `Finding` is a rule diagnostic, not an AI
   finding and not feedback that a developer fixed something.
4. **Main report.** Produce and retain immutable `report.main.json` plus
   `report.main.md` before Rule Discovery, with `ruleDiscovery.status: NOT_RUN`.
   Follow the review schema; include independent coverage and final coverage,
   analyzer/algorithm definitions, all six metric rows for each touched entity,
   findings with snapshot-specific file/line evidence and minimal recommendations,
   `skips`, and a justified verdict. Use the bundled
   [review_artifacts.py](../../scripts/review_artifacts.py) helper:
   `freeze independent.json independent.frozen.json` before metric calls;
   `validate report.json --independent independent.frozen.json` and
   `render report.json --independent independent.frozen.json --output report.md`
   after assembly (prefix each command with Python and the resolved helper path).
   A frozen artifact cannot be overwritten with changed content. Absent metric
   IDs stay absent in JSON `metrics[]` with an explicit skip; the renderer displays
   their `MISSING` cells without manufacturing comparison data or definitions.
   Writing review artifacts is allowed; writing history is delegated to Core tools.
5. **Rule Discovery.** Apply `rule-discovery` after the main report is retained.
   Retain its outcome separately in `discovery.json`, then create NEW
   `report.final.json` / `report.final.md` artifacts containing its machine status
   in `ruleDiscovery`. Never overwrite the retained main/frozen files. Never
   re-append the display report after discovery: Core receives a single stable
   pre-discovery history payload, as described in `rule-discovery`. A history error must preserve the
   report and measured results. Show rule-discovery prose only for a newly proposed
   candidate; otherwise the report's machine status/operational limitations suffice.

## Completeness and the response

- `INCOMPLETE` takes precedence over `WARN` and `PASS` when any selected source,
  changed entity, mandatory review stage, metric, or required batch could not be
  processed. Unknown coverage is itself a limitation; do not invent entity counts.
- `WARN` means the required review is complete and has justified findings/signals.
  `PASS` means the required review is complete with no such findings under this
  policy; it does not establish ideal code. `FAIL` is not an MVP verdict.
- Check all six metrics independently of the server's `ok` status and separately
  for each language/entity in scope. Derive completeness from actual returned
  measurements and coverage, never from a hardcoded historical JAR limitation.
  The integrated Python adapter supports all six with `complexipy==8.3.0` in the
  selected Python; an unavailable/wrong cognitive engine returns `ERROR` while
  preserving the other five. Java now supplies all six for methods and ordinary
  constructors with bodies. A complete Python-only, Java-only or mixed review may
  therefore be `PASS` or `WARN`. Bodyless Java declarations and compact record
  constructors retain their actual `UNSUPPORTED` measurements; these require
  `INCOMPLETE` under the six-metric policy. A legitimate `ENTITY_ABSENT` side for
  an addition/deletion does not alone make the review incomplete.
- Matching belongs to Core. Python parameter renames may now be `MATCHED` and
  have real deltas; do not apply the earlier signature-only pairing assumption.
  Preserve `AMBIGUOUS`/`UNVERIFIED` groups and their unavailable values. For a
  legacy response without matches, disclose the absent metadata and use only
  explicitly returned entity/comparison facts. Label final coverage
  `entityUnit: LEGACY_METRIC_ENTITY` for distinct reported path/entity keys, not
  asserted Core match groups. Unknown grouping or coverage is a limitation, not
  permission to invent matches or rewrite the frozen stage.
- Java positional anonymous/initializer identities may be `UNVERIFIED` even with
  two raw `AVAILABLE` measurements. Preserve `matchingWarning`, comparison
  `UNAVAILABLE`, and null delta. Do not subtract the values or reinterpret an
  `UNVERIFIED` diagnostic as a confirmed change. This matching limitation requires
  `INCOMPLETE`; the measurements themselves remain useful source evidence.
- LSP is optional: unavailable definition/references must be stated but do not
  invalidate otherwise complete AST/metric review. History failure alone likewise
  does not change an otherwise complete main-review verdict.
- If AI review or correlation fails after static analysis, return the retained
  static results and mark the missing mandatory stage `INCOMPLETE`.

Respond in the user's language. Link findings to committed snapshots (or give
`SHA:path:startLine-endLine` plus a verified local link) so a dirty working tree
cannot silently change their meaning. Include the JSON/Markdown artifacts or their
paths, the scope, verdict, coverage, findings, metric table, and material skips.
Never apply source edits, install hooks, activate proposed rules, or record human
feedback merely because a review was requested.
