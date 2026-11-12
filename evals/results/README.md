# Фактические результаты проверок

## Объединённая версия 0.4.0

Новые результаты Java6/Python6 + history сохраняются отдельно от приведённых ниже
исторических запусков. Установка текущего пакета: [INSTALL.md](../../plugin/INSTALL.md).
Source/JAR hashes и уровень выполнения в каждом receipt относятся к его запуску.

- [plugin-release-0.4.0.json](plugin-release-0.4.0.json): переносимый ZIP, свежая
  сборка, установка в чистый профиль, 15 инструментов и Java/Python-метрики из
  установленного кэша. Пользовательская копия обновлена до 0.4.0; отдельный
  native Codex smoke использует установленный плагин без ручного MCP override.
  Общий source runner: 18/20 в текущем дереве; две проверки прошли отдельно с
  неизменёнными скриптами и каноническим fixture из HEAD, удалённым из docs.
- unified-integration-build.json: свежий объединённый JAR, 20/20 checks, CP1251.
- codex-unified-approval-denied.json: реальный Codex WARN/24 comparisons;
  history write отклонён политикой never, основной отчёт сохранён.
- codex-unified-integration.json: новый Codex + repository Skills + explicit MCP,
  13 native calls, Java6/Python6, WARN/24 comparisons, validated report и history
  restart/replay PASS. Installed plugin cache и production history не менялись.

## Интеграция Python, 12.11.2026

| Файл | Уровень и смысл |
|---|---|
| python-integration-build.json | Свежий bundled build и 8 наборов проверок, PASSED |
| protocol-python-integration.json | 4 реальных MCP protocol-сценария; точные измерения и matches |
| agent-python-integration-summary.json | Naming WARN и 2 synthetic history assessment, fresh agent + source-built real JAR |
| agent-python-integration.json | Семантическая проверка Naming-артефакта; сама по себе не доказывает его автора |
| codex-python-integration.json | Установленный 0.3.2 → Codex → 6 MCP calls → Python-only PASS |
| codex-python-degraded.json | Более ранний Codex INCOMPLETE / CogC ERROR, пять значений сохранены |
| python-launcher.json | 4 реальные проверки конфигурации Python, STDIO и lifecycle launcher |

В исторических Python receipts синтетические history outcomes — решение Skill без persistence; в том JAR history Tools отсутствуют.
PASS теста/верификатора следует отличать от вердикта кода. В этих запусках история
была UNAVAILABLE.

## Исторический baseline 0.2.0

agent-forward.json, codex-live.json и protocol-baseline.json отражают прежний JAR ec6a3ed.
Они сохранены неизменными и не доказывают готовность нового пакета. У старого JAR
не хватало Python-метрик, поэтому соответствующие code-review verdicts INCOMPLETE корректны
для того исторического состояния. Абсолютные локальные пути и хеши в файлах — receipts
выполненных запусков; новые проверки пишите в новые каталоги и файлы.

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
