# Evaluation evidence

`scenarios.json` defines six scenarios. Protocol results, model results and manual
observations are different evidence levels. A successful protocol run does not
prove Codex discovery, Skill use or Rule Discovery persistence.

Run the reproducible commands in `evals/README.md`. Every fresh result starts as
`NOT_RUN`. Record a failed/unavailable run as such; never replace it with the
expected answer. `protocol.json` is generated only from the real Java JAR.

Synthetic history fixtures are labelled test data. They are not real developer
feedback. Historical 0.1.3/0.1.4 recordings predate history tools; the current JAR
provides get_review_history/update_review_history. Persistence and replay checks
are available through scripts/history_test.py and the --with-history agent run.

`java-six-metrics-skill.json` records the 12.11.2026 fresh-agent run with the
repository Skill and real process-local MCP server 0.1.3: two Java methods,
12 numerical comparisons, verified freeze ordering, valid report schema and
final `WARN` with complete coverage. It is separate from installed-plugin and
synthetic history evidence. Reproduce with `scripts/llm_java_skill_e2e.py`.

`unified-mcp-api.json` records a fresh Codex read-only session against the real
STDIO server 0.1.4. Native calls to get_changes, analyze_changes and
get_symbol_context retrieved mixed Java/Python metrics and committed context for
both languages. Invalid Python input produced partial warnings while healthy
results were retained. Reproduce with `scripts/mcp_codex_smoke.py`.

`jdtls-navigation.json` records real Eclipse JDT LS 1.54.0 navigation via MCP on a
two-file Java project with src/main/java layout: cross-file definition/references,
UTF-16 positions, unchanged project files and six metrics retained with missing
or broken JDT LS configuration. Archive URL/hash and the tested JAR hash are
included. Controlled failure/lifecycle checks are separate in lsp_client_test.py.
