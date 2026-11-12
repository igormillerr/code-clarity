# CodeClarity LLM evaluations

## Unified package 0.4.0

The integrated server 0.1.7 combines Java6, Python6, exact Core match groups,
changed-line coverage and review/candidate persistence. Run `mvn verify` with
the interpreter configured by `requirements-llm-dev.txt`. This includes real
MCP tests and deterministic artifact checks; it does not invoke a model.

For a fresh agent, both languages and history persistence:

```bash
python scripts/llm_java_skill_e2e.py --languages java python --with-history --output .codeclarity/evals/unified-new
```

Despite its historical filename, the script accepts either or both languages.
It uses repository Skills and an explicit process-local MCP server, preserves
native Codex events, validates the report and checks history restart/replay.
It does not install or update a plugin, change home configuration, manufacture
human feedback or activate a rule. Use a new output directory for each run.
`--with-history` explicitly approves only `update_review_history` on the
process-local server bound to that newly created disposable repository.
Other tools retain their normal approval behavior; without the flag there is
no override and the prompt prohibits writes. This uses the documented
[per-tool approval setting](https://learn.chatgpt.com/docs/config-file/config-reference).

The recordings below retain their original version and scope.

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

## Historical Python integration 0.3.2

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

## Unified MCP API smoke checks

```bash
python3 scripts/mcp_smoke_test.py target/codeclarity-mcp.jar
python3 scripts/mcp_codex_smoke.py --output .codeclarity/evals/api-run --jar target/codeclarity-mcp.jar
```

The first command is a standalone real-STDIO smoke check: handshake, discovery,
get_changes, mixed analyze_changes, get_symbol_context for both languages,
committed source and line ranges, partial/truncation warnings, argument errors,
and compatibility with compact context tools. The second starts a fresh Codex
session with read-only sandboxing, default model and existing authentication;
pass `--codex /path/to/codex` if needed. It records native MCP calls and verifies
all three required tools were called, both languages retained metrics, and both
contexts came from the resolved commit. The MCP configuration is process-local.

The 12.11.2026 run is retained in
[`results/unified-mcp-api.json`](results/unified-mcp-api.json): PASS, four native
Codex MCP calls covering all three required operations and both languages.

## Optional JDT LS navigation

```bash
python3 scripts/lsp_client_test.py target/codeclarity-mcp.jar
python3 scripts/lsp_smoke_test.py
python3 scripts/lsp_smoke_test.py --jdtls-home /path/to/extracted/jdtls --java /path/to/jdk/bin/java --output .codeclarity/evals/jdtls-live.json
```

The controlled protocol peer checks framing, duplex configuration requests,
Location/LocationLink, references, startup/request/write timeouts, invalid input,
stderr draining, graceful shutdown and forced process termination. It does not
stand in for the last command, which starts real JDT LS through MCP and verifies
cross-file definition/references, UTF-16 positions after Unicode, a clean working
tree and metric isolation from failed startup. No Maven/Gradle import is enabled.
The tools explicitly return WORKTREE scope, not a committed snapshot.

[`results/jdtls-navigation.json`](results/jdtls-navigation.json) retains the
12.11.2026 real-server run using JDT LS 1.54.0, a SHA-256-verified official archive,
JDK 25 and server 0.1.6. Both semantic requests and the metric-isolation checks passed.

## Live Java Skill check with six metrics

For server 0.1.3, run a fresh agent against the repository's current
`readability-review` Skill and actual MCP tools:

```bash
python3 scripts/llm_java_skill_e2e.py --output .codeclarity/evals/java-skill-run
python3 scripts/llm_java_skill_e2e.py --output .codeclarity/evals/java-skill-run --verify-only
```

Pass `--codex /absolute/path/to/codex` if the CLI is not on PATH. The run uses
existing CLI authentication and its default model. It creates a disposable Java-only
Git fixture with two methods, configures the bundled MCP JAR for this process only,
and directs the agent to the current Skill without providing the expected verdict.
It does not install/update a plugin or change the home repository configuration.
Use a new output directory for every agent run; verification can be repeated.

`events.jsonl` retains raw CLI/MCP events. `evidence.json` verifies actual MCP calls,
freeze before analysis starts, six numerical metric comparisons for each method,
exact preservation of returned values/definitions/deltas, report coverage and
`PASS`/`WARN` completeness, final Markdown rendering, and an unchanged input fixture.
Full Draft 2020-12 report-schema validation uses the validator bundled in the JAR;
its output is retained in `schema-validation.log`. The agent creates the independent,
main, discovery and final artifacts under `artifacts/`.

This checks the Skill and real MCP in a fresh agent, separately from the historical
installed-plugin runs below. It does not verify an installed plugin cache or history
persistence, and a single successful run does not guarantee future model behavior.

The verified 12.11.2026 run is retained in
[`results/java-six-metrics-skill.json`](results/java-six-metrics-skill.json):
two Java files/methods, 12 numerical comparisons, freeze before analysis, complete
coverage, one source-backed finding and final verdict `WARN`. History discovery
is `UNAVAILABLE`; it does not make the main Java review incomplete.

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

For a complete fresh-agent Java review with real MCP history writes, restart and
idempotent replay checks, plus optional real JDT LS navigation, run:

```sh
python3 scripts/llm_java_skill_e2e.py --codex /path/to/codex --output .codeclarity/evals/full-workflow-01 --with-history --jdtls-home /path/to/jdtls --jdtls-java /path/to/java
```

The runner uses existing CLI authentication/default model and a process-local MCP
configuration. History is written only in its disposable fixture repository; no
human confirmations are manufactured. Omit both JDT LS options to test the core
review/history workflow alone. Without `--with-history`, history writes remain
forbidden. Retain `events.jsonl`, reports, `evidence.json` and the fixture history.
Verification checks the frozen review precedes metrics, all 12 Java comparisons
match MCP receipts, the final report schema/Markdown, two fresh-process history
reads, and unchanged file bytes/mtime and counters on an identical review replay.
With JDT LS configured, actual native agent definition/references calls must
resolve the unchanged caller to the reviewed declaration and back. This checks
the repository Skill/JAR, not the installed plugin cache.

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
