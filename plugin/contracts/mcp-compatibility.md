# MCP compatibility and team handoff

Status: **implemented unified MCP API**, plugin 0.4.0 / server 0.1.7.
Owner: Java / LLM Engineer for plugin/Skills/review format; Java Core engineer for
MCP schemas, snapshots, measurements, persistence and feedback authorization;
Python engineer for Python analysis. Discover the actual tool schemas before use.

## Current server 0.1.7

The server includes the six Java metrics and both language adapters behind the
same LanguageSupport / AnalysisService boundary. Current unified integration
receipts cover this 0.1.7 JAR; older historical eval receipts retain their original
0.1.1 Python-only runtime and must not be treated as current package results.

| Operation | Actual tool and required arguments |
|---|---|
| Resolve mixed scope | `get_changes(baseRef, headRef)` |
| Mixed measurements | `analyze_changes(baseSha, headSha, paths?)` |
| Committed source and AST context | `get_symbol_context(commitSha, path, line)` |
| Read persistent review memory | `get_review_history()` |
| Append review / merge category metadata | `update_review_history(review?, categories?)` |
| Store a proposed rule with existing evidence | `propose_rule_candidate(candidate)` |
| Optional WORKTREE definition | `get_symbol_definition(path,line,column)` |
| Optional WORKTREE references | `find_symbol_references(path,line,column,includeDeclaration?)` |
| Legacy compact AST context | `inspect_symbol_ast(commitSha, path, line)` |
| Resolve Java scope | `list_java_changes(baseRef, headRef)` |
| Resolve Python scope | `list_python_changes(baseRef, headRef)` |
| Java measurements | `analyze_java_changes(baseSha, headSha, paths?)` |
| Python measurements | `analyze_python_changes(baseSha, headSha, paths?)` |
| Java AST context | `inspect_java_method(commitSha, path, line)` |
| Python AST context | `inspect_python_function(commitSha, path, line)` |

The list response has `baseSha` (merge-base), `headSha`, `status`, `warnings`, `files` with old/new
paths and inclusive one-based `baseLines`/`headLines`. Match snapshots between
languages; do not mix commits across batches. Analysis batches contain <=50
changed paths. Rename selection uses newPath; deletion selection uses oldPath.
Current scope is committed code, not staged/worktree/untracked.
Mixed tools choose the adapter using supports(path); no language argument is
needed. Language tools restrict the same service to one adapter and remain
available for compatibility. A cross-language rename becomes separate deletion
and addition entries, selected by the old and new paths respectively; entities
are not matched between languages. Each entry counts towards the 50-entry limit.

Analyze returns `{baseSha,headSha,status,files,warnings}`. Each file contains
`language`, `changedMethods`, diagnostic `findings`, numerical `metrics`, and Core `matches`. Keep diagnostic
Finding `{rule,line,column,message}` separate from an AI Finding in
[review.schema.json](review.schema.json). `RESOLVED` is a static rule status,
not a confirmed human `FIXED` event. `ok` does not imply all six metrics exist.
File read/adapter/comparison RuntimeExceptions are isolated: retain the file entry,
add a path-specific warning and return `partial` without discarding healthy files.
An adapter's complete=false also forces partial even with no supplied warnings.
Failed versions have no fabricated numeric value or delta. Request/SHA/routing
configuration errors are tool errors rather than successful empty reports.

Each analysis file also has additive `coverage: {base, head}`. Each side is
`{status, outsideEntityLines, reason}`: `COMPLETE` means changed lines fall within
supported entity ranges; `OUTSIDE_SUPPORTED_ENTITIES` lists inclusive one-based
ranges outside those entities (for example fields, imports and initializers);
`UNKNOWN` means analysis failed and coverage cannot be established. An absent
file side has COMPLETE coverage with no ranges. Request `ok` is independent of
this coverage and does not establish a complete review. Explain uncovered code
and inspect it separately; do not silently count it as reviewed by method metrics.
Coverage is line-based, so it cannot distinguish declarations sharing a line.
Copy supplied coverage into report `fileCoverage`, adding only `path`, `oldPath`,
`newPath` and retaining exact `base`/`head` sides. Record outside/unknown coverage
in skips. The current entity-metric policy requires INCOMPLETE for either status,
even when source inspection was useful and the file has no metric entities.

Java anonymous owners include a variable-based label and lexical ordinal;
enum-constant owners include the constant name. Named methods retain their
existing signatures. Unlabelled expressions, repeated local names and initializer
owners use lexical position and cannot establish cross-snapshot identity. Their
comparisons are UNAVAILABLE with null delta and a path/entity warning; raw side
measurements remain available. Their diagnostic changes are UNVERIFIED. Never
derive a delta from these raw values merely because the definitions match.

Each metric comparison is `{entity,metric,status,before,after,delta}`. Add only
the owning file's path when normalizing into a review; preserve the two MetricValue
objects and delta from MCP. Definitions use `{id,language,analyzer,algorithm}`:
analyzer includes its version, algorithm includes algorithm/settings version.
Do not rename these to a guessed future shape. Before/after SHA live in scope.
The merged server supplies all six metric IDs for Java and Python. Java bodyless
declarations expose SLOC/parameters and UNSUPPORTED body metrics; compact record
constructors expose UNSUPPORTED PMD complexity metrics. Python CogC uses strictly
`complexipy==8.3.0` in the selected interpreter; missing/wrong-version support is
ERROR while preserving five other measurements. Actual per-entity values and
coverage determine completeness; complete Java-only, Python-only or mixed reviews
can be PASS/WARN. Preserve historical receipts with their original availability.

## Entity matches and coverage

Each `files[].matches[]` is `{key,status,before,after}`. The two arrays retain all
SourceEntity candidates with their `signature`, `lines`, `matchingKey`, and
`matchingAmbiguous`, and optional nullable `matchingWarning`. Normalize into report `entityMatches` by adding only owning
`path`, `oldPath` and `newPath`, leaving the match payload unchanged. `path` follows
the normal selection rule: newPath for an existing/renamed/added file, oldPath for
a deletion. Before ranges belong to oldPath/baseSha; after ranges to newPath/headSha.

The Core statuses are MATCHED, ADDED, REMOVED, AMBIGUOUS and UNVERIFIED. Matching is
within the Git file pair. Python qualified-name keys exclude parameters, so
`subtotal(line_items)` to `subtotal(a)` can be one MATCHED group with actual
before/after/delta. Java retains its named syntactic identities; positional anonymous/initializer identities remain UNVERIFIED. Function or
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


`get_symbol_context` returns `{commitSha,path,language,status,signature,lines,source,calls,truncated,warnings}`.
The source is the complete entity declaration at the inclusive one-based range
in the specified commit, with LF line endings and no trailing newline. A truncated
call list sets `truncated:true`, `status:partial` and a warning without truncating
the source. The legacy `inspect_*` operations retain their compact signatures,
lines, calls and enclosing if branches, without full source or semantic definitions.
Read surrounding code and diff using read-only Git
commands against the resolved SHAs; never substitute worktree source. Optional LSP
tools explicitly operate on WORKTREE, with one-based UTF-16 line/column input and
end-exclusive returned ranges. Use them as commit evidence only after verifying
the relevant working-tree files match the reviewed snapshot. Missing providers,
startup failure and timeouts return unavailable/timeout warnings without blocking
metrics. Maven/Gradle imports and automatic builds are disabled in the minimal JDT
integration. Returned locations include URI, path (relative inside repo, absolute
outside, null for non-file URIs), external flag and range. LSP unavailability alone need not invalidate a
complete AST review. Missing required code coverage or measurements does.

## Universal tools and remaining target tools

Server 0.1.7 implements `get_changes`, `analyze_changes`, `get_symbol_context`. Prefer them when discovered,
using their advertised schemas and returned snapshot format. Retain the existing
`inspect_symbol_ast` and language tools as a compatibility path; do not call speculative tools or guess arguments.
`get_symbol_definition` and `find_symbol_references` are optional/context only;
they require separately configured JDT LS for Java and never accept commitSha.
The packaging launcher retains `~/.codeclarity/python-path.txt` and optionally
reads `jdtls-home.txt` / `jdtls-java.txt` in that same directory, each one absolute
UTF-8 path. Explicit CODECLARITY_PYTHON / CODECLARITY_JDTLS_HOME /
CODECLARITY_JDTLS_JAVA environment values take precedence when the host preserves
them. File selectors work when the plugin host filters custom environment values;
restart the server after changing them. Real JDT requires an extracted matching
platform distribution and its supported Java runtime; no server is installed or
started until navigation is requested. Invalid/missing configuration degrades
navigation explicitly and does not block metrics.

## Persistent history API

`get_review_history({})` returns the whole repository-local envelope defined in
[review-history.schema.json](review-history.schema.json), including revision,
immutable reviews, derived findings/categories/statistics/examples and feedback.
No file is created on an empty read. `update_review_history` accepts only the
[history-update.schema.json](history-update.schema.json) request: `review` (a full
review-schema report with pre-discovery `NOT_RUN`) and/or category metadata
`{categoryId,name,description?}`. Replay an identical review ID/payload safely;
conflicting payloads or a duplicate scope with another ID are rejected. Read-back
uses get_review_history and client-side reviewId lookup. A successful receipt is
`{status: saved|unchanged, revision, historyPath, statistics}`.

New history findings are DETECTED; the immutable report retains PENDING_FEEDBACK.
Only the explicit local operator CLI records FIXED/REJECTED with author/evidence;
MCP updates cannot supply confirmations or counters. The latest feedback event
per finding determines derived state, preserving prior events. This is a local
operator trust boundary, not authentication of an agent-supplied confirmedBy.

Both stored/input JSON are validated; derived state is checked against its source
reviews/feedback. Updates use a cross-process lock, forced temporary file and
atomic replacement without a non-atomic fallback. Invalid existing JSON is never
silently reset.

History operation mapping:

| Tool | Proposed request | Result / invariant |
|---|---|---|
| `append_review_result` | Current equivalent is `update_review_history({review,categories?})` | No extra tool is needed |
| `record_feedback` | Currently local operator CLI only | No model-supplied feedback through MCP |
| `propose_rule_candidate` | [rule-candidate.schema.json](rule-candidate.schema.json): `{candidate}` | Implemented; immutable candidateId, status always PROPOSED; no rule activation |

Production candidates use the same named fields as the general LLM candidate:
candidateId, categoryId, status, title, description, supportingFindingIds,
confirmedFeedbackIds, examples and exceptions. A proposal must reference at least
three distinct stored source/snapshot occurrences in one known category, with at
least two distinct occurrences whose latest operator feedback is FIXED. Every
cited feedback event must belong to a supporting finding and its review, with
HUMAN/LOCAL_CLI provenance and nonblank confirmation evidence. Old FIXED events
superseded by later decisions are insufficient. No MCP call can supply those
events, counters, activation state or synthetic production evidence.

Examples are objects with findingId referencing support; optional reviewId,
snapshotId, location, description, recommendation and evidence must exactly match
the immutable stored finding. Replaying identical ID/payload returns unchanged;
conflicting payloads are rejected. Within a category, matching normalized title
or supporting-ID set returns unchanged and the original candidateId; semantic
equivalence beyond these checks remains the Skill's responsibility. Receipts add
candidateId and candidateStatus: PROPOSED to the normal storage receipt. A saved
proposal never activates a rule or increments finding counts. Later feedback can
change current eligibility without rewriting historical proposal provenance.

The actual Core schemas take precedence after coordination. The envelope in
[history.schema.json](history.schema.json) remains the general/synthetic interchange, not a
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
