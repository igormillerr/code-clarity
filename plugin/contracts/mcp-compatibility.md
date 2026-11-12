# MCP compatibility and team handoff

Status: **proposed exchange v1**, not an agreement or implementation by other developers.
Owner: Java / LLM Engineer for plugin/Skills/review format; Java Core engineer for
MCP schemas, snapshots, measurements, persistence and feedback authorization;
Python engineer for Python analysis. Discover the actual tool schemas before use.

## Current server 0.1.4

The server includes the six Java metrics and both language adapters behind the
same LanguageSupport / AnalysisService boundary. The checked-in historical eval
receipts refer to the older 0.1.1 JAR from feature/python ec6a3ed.

| Operation | Actual tool and required arguments |
|---|---|
| Resolve mixed scope | `get_changes(baseRef, headRef)` |
| Mixed measurements | `analyze_changes(baseSha, headSha, paths?)` |
| Committed source and AST context | `get_symbol_context(commitSha, path, line)` |
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
`language`, `changedMethods`, diagnostic `findings`, and numerical `metrics`. Keep diagnostic
Finding `{rule,line,column,message}` separate from an AI Finding in
[review.schema.json](review.schema.json). `RESOLVED` is a static rule status,
not a confirmed human `FIXED` event. `ok` does not imply all six metrics exist.
File read/adapter/comparison RuntimeExceptions are isolated: retain the file entry,
add a path-specific warning and return `partial` without discarding healthy files.
An adapter's complete=false also forces partial even with no supplied warnings.
Failed versions have no fabricated numeric value or delta. Request/SHA/routing
configuration errors are tool errors rather than successful empty reports.

Each metric comparison is `{entity,metric,status,before,after,delta}`. Add only
the owning file's path when normalizing into a review; preserve the two MetricValue
objects and delta from MCP. Definitions use `{id,language,analyzer,algorithm}`:
analyzer includes its version, algorithm includes algorithm/settings version.
Do not rename these to a guessed future shape. Before/after SHA live in scope.
Java has numeric CC, CogC, function SLOC, max nesting depth, parameter count and
return count. Bodyless declarations expose SLOC/parameters and UNSUPPORTED body
metrics; compact record constructors expose UNSUPPORTED PMD complexity metrics.
Definitions and scope rules are documented in the main README. Python has numeric
CC and explicit UNSUPPORTED CogC; its SLOC, nesting, parameters and returns remain
missing. A review requiring all six Python metrics must therefore report INCOMPLETE,
even if empty AI findings or a server `ok` would otherwise suggest PASS.

`get_symbol_context` returns `{commitSha,path,language,status,signature,lines,source,calls,truncated,warnings}`.
The source is the complete entity declaration at the inclusive one-based range
in the specified commit, with LF line endings and no trailing newline. A truncated
call list sets `truncated:true`, `status:partial` and a warning without truncating
the source. The legacy `inspect_*` operations retain their compact signatures,
lines, calls and enclosing if branches, without full source or semantic definitions.
Read surrounding code and diff using read-only Git
commands against the resolved SHAs; never substitute worktree source. No LSP or
history tools exist in this JAR. LSP unavailability alone need not invalidate a
complete AST review. Missing required code coverage or measurements does.

## Universal tools and remaining target tools

Server 0.1.4 implements `get_changes`, `analyze_changes`, `get_symbol_context`. Prefer them when discovered,
using their advertised schemas and returned snapshot format. Retain the existing
`inspect_symbol_ast` and language tools as a compatibility path; do not call speculative tools or guess arguments.
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
