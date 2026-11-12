# Фактические результаты проверок

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

Синтетические history outcomes — решение Skill без persistence; реальных history Tools нет.
PASS теста/верификатора следует отличать от вердикта кода. В production history остаётся
UNAVAILABLE. Полный текущий статус и команды: [llm-status.md](../../docs/llm-status.md).

## Исторический baseline 0.2.0

agent-forward.json, codex-live.json и protocol-baseline.json отражают прежний JAR ec6a3ed.
Они сохранены неизменными и не доказывают готовность нового пакета. У старого JAR
не хватало Python-метрик, поэтому соответствующие code-review verdicts INCOMPLETE корректны
для того исторического состояния. Абсолютные локальные пути и хеши в файлах — receipts
выполненных запусков; новые проверки пишите в новые каталоги и файлы.
