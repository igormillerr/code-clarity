# MCP compatibility and team handoff

Status: **proposed exchange v1**, not an agreement or implementation by other developers.
Owner: Java / LLM Engineer for plugin/Skills/review format; Java Core engineer for
MCP schemas, snapshots, measurements, persistence and feedback authorization;
Python engineer for Python analysis. Discover the actual tool schemas before use.

## Integrated JAR from feature/python-metrics-integration dc9d957

| Operation | Actual tool and required arguments |
|---|---|
| Resolve Java scope | `list_java_changes(baseRef, headRef)` |
| Resolve Python scope | `list_python_changes(baseRef, headRef)` |
| Java measurements | `analyze_java_changes(baseSha, headSha, paths?)` |
| Python measurements | `analyze_python_changes(baseSha, headSha, paths?)` |
| Java AST context | `inspect_java_method(commitSha, path, line)` |
| Python AST context | `inspect_python_function(commitSha, path, line)` |

The list response has `baseSha` (merge-base), `headSha`, `files` with old/new
paths and inclusive one-based `baseLines`/`headLines`. Match snapshots between
languages; do not mix commits across batches. Analysis batches contain <=50
changed paths. Rename selection uses newPath; deletion selection uses oldPath.
Current scope is committed code, not staged/worktree/untracked.

Analyze returns `{baseSha,headSha,status,files,warnings}`. Each file contains
`changedMethods`, diagnostic `findings`, numerical `metrics` and Core `matches`. Keep diagnostic
Finding `{rule,line,column,message}` separate from an AI Finding in
[review.schema.json](review.schema.json). `RESOLVED` is a static rule status,
not a confirmed human `FIXED` event. `ok` does not imply all six metrics exist.

Each metric comparison is `{entity,metric,status,before,after,delta}`. Add only
the owning file's path when normalizing into a review; preserve the two MetricValue
objects and delta from MCP. Definitions use `{id,language,analyzer,algorithm}`:
analyzer includes its version, algorithm includes algorithm/settings version.
Do not rename these to a guessed future shape. Before/after SHA live in scope.

The integrated Python adapter supports all six metric IDs. CogC uses strictly
`complexipy==8.3.0` in the interpreter selected by `CODECLARITY_PYTHON`; missing or
wrong-version cognitive support returns `ERROR` with a reason while preserving
the other five measurements. The worker's `complete` describes AST/entity/finding
coverage, not universal metric availability. Warnings can make the Core report
`partial` while successful individual measurements remain usable.

Java currently supplies CC and CogC, with the four structural metrics still absent.
This describes the integrated artifact, not a fixed rule for future releases:
derive completeness from actual responses for the selected scope. A Python-only
review with complete source review and six available metrics may be PASS or WARN.
Unselected Java files do not make it incomplete. Missing mandatory metrics for
selected entities require INCOMPLETE, regardless of a server `ok`.

Archived ec6a3ed results used Python CC plus UNSUPPORTED CogC and lacked four
structural metrics. Preserve those reports as historical evidence; do not apply
their availability or signature-pairing assumptions to this new JAR.

## Entity matches and coverage

Each `files[].matches[]` is `{key,status,before,after}`. The two arrays retain all
SourceEntity candidates with their `signature`, `lines`, `matchingKey`, and
`matchingAmbiguous`. Normalize into report `entityMatches` by adding only owning
`path`, `oldPath` and `newPath`, leaving the match payload unchanged. `path` follows
the normal selection rule: newPath for an existing/renamed/added file, oldPath for
a deletion. Before ranges belong to oldPath/baseSha; after ranges to newPath/headSha.

The Core statuses are MATCHED, ADDED, REMOVED, AMBIGUOUS and UNVERIFIED. Matching is
within the Git file pair. Python qualified-name keys exclude parameters, so
`subtotal(line_items)` to `subtotal(a)` can be one MATCHED group with actual
before/after/delta. Java continues exact syntactic-signature matching. Function or
owner renames and cross-file moves are not automatically paired. Do not recreate
matching in a Skill, parse keys to manufacture a pair, or substitute metric zeros.
Use returned comparisons and their side definitions/statuses; ambiguous or
unverified matching may leave some values unavailable without erasing valid ones.

Independent Review coverage uses `entityUnit: SNAPSHOT_ENTITY`, counting source
occurrences separately on base and head. It is frozen before current analysis.
Final coverage uses `entityUnit: MATCH_GROUP`, counting the returned logical Core
groups once, including explicit unresolved groups when reporting omissions. These
denominators can differ: two reviewed snapshot declarations can become one group.
Never rewrite the frozen counts to make them equal. Reviewed/analyzed counts mean
actually completed work; preserve omissions and unknown counts explicitly.

If an older server does not expose matches, state that the matching metadata is
unavailable and retain the comparisons it actually returned. Do not label guessed
groups MATCH_GROUP. Distinct reported path/entity keys can be counted as
`entityUnit: LEGACY_METRIC_ENTITY`, explicitly identifying comparison coverage
rather than asserting source pairing. If the total affected-entity coverage cannot
be established, use null counts and INCOMPLETE. Input Tool names and earlier
result fields remain available.

Inspection provides signatures, lines, calls and enclosing if branches, not full
source or semantic definitions. Read full code and diff using read-only Git
commands against the resolved SHAs; never substitute worktree source. No LSP or
history tools exist in this JAR. LSP unavailability alone need not invalidate a
complete AST review. Missing required code coverage or measurements does.

## Target tools, not implemented by this plugin

Prefer `get_changes`, `analyze_changes`, `inspect_symbol_ast` when discovered,
using their advertised schemas and returned snapshot format. Retain the existing
tools as a compatibility path; do not call speculative tools or guess arguments.
`get_symbol_definition` and `find_symbol_references` are optional/context only.

Proposed history operations for Core review:

| Tool | Proposed request | Result / invariant |
|---|---|---|
| `get_review_history` | Optional bounded category/review filters as advertised | Schema v1 envelope; errors explicit, no source dumps |
| `append_review_result` | `{review, categories}` | Same reviewId/findingId is idempotent; conflicting payload rejected, not silently overwritten |
| `record_feedback` | `{feedback}` from explicit developer decision or verified external process | Core verifies provenance; an agent-supplied `confirmedBy` string is not authorization |
| `propose_rule_candidate` | `{candidate}` | Idempotent candidateId, status always PROPOSED; no rule activation |

The actual Core schemas take precedence after coordination. The envelope in
[history.schema.json](history.schema.json) is an interchange proposal, not a
security boundary. Core must obtain/verify human feedback independently of model
assertions; the Skill never records its own findings as human-confirmed.
Do not write `.codeclarity/review-history.json` directly to compensate for missing
tools. Preserve the main report and record history UNAVAILABLE or ERROR.

Use `PENDING_FEEDBACK` for new AI findings. Pending, disappeared findings and static
RESOLVED diagnostics never count as fixed. Count distinct occurrences, not duplicate
rows, and the latest authoritative decision per finding, not repeated feedback
events. Candidate requires >=3 distinct findings of one reusable category, >=2
distinct confirmed fixed findings, and no equivalent active/proposed rule. Cite
finding IDs, feedback IDs, examples and exceptions. Prepared feedback with
`source: DEMO_FIXTURE` and `synthetic: true` is valid only in an explicitly synthetic
demonstration; never merge it into real project history or call it user feedback.

## Review artifacts

[review.schema.json](review.schema.json) describes the final report. Before
calling analyze, save the independent stage with status, reviewId, scope,
coverage (`filesExpected/filesReviewed/entitiesExpected/entitiesReviewed`) and
findings; freeze it using the packaged artifact helper. Final
`independentReview.artifact` references that immutable artifact. Findings have
stable IDs, explicit snapshot, evidence and pending feedback. Deleted-code
findings must use the base snapshot and old path. At correlation preserve the
original frozen observation; record any changed conclusion explicitly.

Scope paths are the selected changed files; languages are explicit. Coverage
counts refer to the selected scope, not the whole repository. Skips contain a
stage and a concrete reason. The six metric IDs are precisely
`cyclomatic_complexity`, `cognitive_complexity`, `function_sloc`,
`max_nesting_depth`, `parameter_count`, `return_count`. Return count has no
automatic diagnostic threshold. Findings and metric signals imply WARN only
after all required stages are complete; any missing required stage wins as
INCOMPLETE. A completely empty selected diff is NO_CHANGES, not a claim of ideal code.

The helpers format/validate LLM artifacts only: they do not calculate metrics,
run analyzers, perform Core comparisons or write history. Keep real MCP call
receipts and independent-freeze events for evaluation of tool order and provenance.

Persistence payload and display outcome are separate artifacts. Retain
`report.main.json/.md` before discovery (`ruleDiscovery.status: NOT_RUN`). After
history category mapping, append immutable `review.history-input.json` with that
same NOT_RUN marker exactly once/replay-identically; if already stored, reuse
its existing payload/category assignments. Store rule candidates via their own
operation. Save `discovery.json` and derive NEW `report.final.json/.md` with the
actual outcome. Never overwrite the main/frozen artifacts or re-append a changed
review only to update its discovery status. NOT_RUN is an intermediate marker,
not a completed discovery outcome. History errors leave the main artifact intact.
