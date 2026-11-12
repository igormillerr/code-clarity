# CodeClarity LLM evaluations

These six cases test the Java / LLM Engineer's workflow. They do not implement or
replace the Python analyzer, Java metrics, MCP transport or Core history store.
Expected labels are in `scenarios.json`; do not pass them to independent-review.

| Case | Expected behavior | Initial real-JAR protocol run | Model behavior |
|---|---|---|---|
| `java-complexity` | Evidence for the deeply nested eligibility decision | PASS | NOT_RUN |
| `python-naming` | Naming issue despite a short, low-complexity calculation | PASS | NOT_RUN |
| `good-code` | Empty independent findings are valid; no forced defect | PASS | NOT_RUN |
| `partial-analysis` | Keep valid file results; mark invalid file and `INCOMPLETE` | PASS | NOT_RUN |
| `history-sufficient` | Three distinct occurrences, two synthetic confirmations → `PROPOSED` candidate | NOT_RUN: history tools absent | NOT_RUN |
| `history-insufficient` | One pending occurrence → silent `NO_SUGGESTION` | NOT_RUN: history tools absent | NOT_RUN |

The first protocol run inside the Windows sandbox failed at Java
`Path.toRealPath` with `AccessDeniedException`. A retry outside that sandbox
passed all four source cases. The checked-in
[`results/protocol-baseline.json`](results/protocol-baseline.json) records the
actual JAR hash, server version, discovered tools and unmodified measurements.
The baseline JAR lacks four required metrics and Python Cognitive Complexity;
the complete review verdict for these fixtures must therefore be `INCOMPLETE`.
MCP protocol PASS does not change that verdict.

## Current integration and historical evidence

The initial table and `protocol-baseline.json` above describe the preserved
`feature/python ec6a3ed` baseline, not the integrated JAR. Do not rewrite those
receipts. After Python integration, a configured Python interpreter with
`complexipy==8.3.0` returns all six Python metrics. A Python-only review can now
be `PASS` or `WARN` when source review/correlation and coverage are complete.
Missing cognitive dependency produces `ERROR` for that metric while preserving
the other five. Java still supplies two metrics, so a mixed Java/Python review
remains `INCOMPLETE` until the Java Core owner supplies its remaining metrics.
Verdicts always follow actual receipts and processing coverage.

New Core responses include `files[].matches`. Copy each unchanged pairing record
to report `entityMatches`, adding only `path`, `oldPath`, and `newPath`. A change
from `subtotal(line_items)` to `subtotal(a)` is now one matched logical group;
keep its real before/after values and delta. Never recreate pairing in the LLM.
Final coverage uses `entityUnit: MATCH_GROUP` and the supplied group count.
Independent coverage uses `SNAPSHOT_ENTITY`, counting reviewed source entities
in each snapshot separately; these counts can differ without rewriting the frozen
review. If old receipts contain no matches, use `LEGACY_METRIC_ENTITY` and do not
invent pairing records. Optional absent units preserve old v1 artifact validation.

New integrated results must have new filenames. Existing JSON under `results/`
is historical evidence with its original JAR hash and limitations.

## Reproduce the protocol results

Requires Java 21+, Git and the Python environment from `requirements-python.txt`.
Run the tests with that environment's interpreter: the MCP test client forwards
`sys.executable` as `CODECLARITY_PYTHON`. Use a new
output directory on each run; the fixture generator refuses to overwrite data.

```powershell
& '.venv/Scripts/python.exe' scripts/llm_evals.py self-test
& '.venv/Scripts/python.exe' scripts/llm_artifact_test.py
& '.venv/Scripts/python.exe' scripts/llm_evals.py protocol --jar plugin/server/codeclarity-mcp.jar --output .codeclarity/evals/run-01
```

The protocol runner initializes the real JAR, discovers tools and calls the
language-specific list/analyze tools for committed fixtures. It verifies exact
snapshot selection, explicit unavailable values, partial-file handling and
retention of valid-file results. Its receipts are in the chosen directory.
This is intentionally a transport/static-analysis test, without AI review.

## Run a real Skill evaluation

Prepare one code scenario in a disposable directory:

```powershell
python scripts/llm_evals.py prepare --scenario python-naming --output .codeclarity/evals/naming-01
```

`manifest.json` reports the absolute `repoRoot`, stable base/head SHAs and the
evaluation request. Point the installed plugin at that `repoRoot` using the
installation instructions. Start a fresh Codex chat, invoke `readability-review`
and pass the request and refs from the manifest. Do not include the labelled
expectations. Keep the committed fixture unchanged during the run.

Preserve:

1. The raw Codex output/tool transcript, separate from any normalized trace.
2. The independent findings artifact and its freeze receipt before analysis.
3. The final JSON/Markdown report and actual MCP result receipts.
4. Manual observations against the rationale in `scenarios.json`.

The artifact checker accepts a normalized trace either as an array or under an
`events` field. Tool events have `{event:"tool_call", tool, arguments, result}`,
where `result` is the exact MCP structured result, not a rewritten summary.
The freeze event has `{event:"independent_review_frozen", artifact, sha256}`;
`plugin/scripts/review_artifacts.py freeze` emits this receipt. A test may also
include the exact frozen `findings` on that event. Preserve event order. Do not
invent a freeze event after a model has already seen current measurements.

```powershell
python scripts/llm_evals.py check --scenario python-naming --report .codeclarity/evals/naming-01/report.json --trace .codeclarity/evals/naming-01/trace.json --repo .codeclarity/evals/naming-01/repo
```

The checker verifies ordering, frozen findings/hash, snapshots, source ranges,
exact supplied match records, match-group coverage, preserved measurements,
missing-data verdicts and scenario expectations. It
does not prove who produced an artifact; retain the raw Codex transcript for
that purpose. Its numerical comparisons validate tool provenance, not metric
algorithms. The Java Core/Python owners test those algorithms separately.
Automated structure/location checks also cannot fully judge the quality of a
recommendation: record whether the finding explains the labelled problem and
whether its proposed change preserves intended behavior.

## Rule Discovery fixtures

`fixtures/history/sufficient.json` and `insufficient.json` are explicitly
synthetic. Every confirmation has `source: DEMO_FIXTURE`, a test identity and
fixture evidence. They must never be represented as real user feedback or
copied into a user's production history.

For an isolated decision evaluation, give a fresh agent the `rule-discovery`
Skill and one history fixture with its scenario request. The request forbids
writes and activation. Save the returned machine object and check it:

```powershell
python scripts/llm_evals.py check --scenario history-sufficient --report candidate-result.json
python scripts/llm_evals.py check --scenario history-insufficient --report no-suggestion-result.json
```

The offline result shape is `{executionLevel:"SYNTHETIC_SKILL_EVAL",
synthetic:true, decision:"RULE_SUGGESTED"|"NO_SUGGESTION", candidate?,
userFacingMessage:""}`. It uses `decision`, never production
`ruleDiscovery.status`. A synthetic `RULE_SUGGESTED` decision must cite existing
distinct finding IDs and at least two confirmed feedback IDs, retain `PROPOSED`
and `synthetic:true`, reuse `opaque_names`, and include examples and exceptions.
`NO_SUGGESTION` has no candidate. Both offline decisions have an empty
user-facing message and must not claim that anything was saved or activated.
An isolated decision evaluation is not proof of MCP history writes, idempotence
or persistence. Production `ruleDiscovery.status: RULE_SUGGESTED` requires a
confirmed real Core persistence receipt; repeat the actual MCP sequence once
the Core owner provides those tools.

## Evidence levels

- `MCP_PROTOCOL`: real JAR and JSON-RPC receipts, no model behavior claim.
- `ARTIFACT_CHECK`: supplied report/trace checked; original producer unverified.
- Live Codex evaluation: retain raw transcript plus the artifact check result.
- Synthetic unit tests: test the evaluator's rejection of fabricated numbers,
  early metric exposure, omitted measurements, false PASS and noisy no-result
  messages. They are never reported as live E2E.

Mark scenarios `NOT_RUN`, `FAIL` or unavailable when that is what happened.
Do not paste expected answers into the actual-results column.
