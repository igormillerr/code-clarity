# Task 03 — фактический результат

Обновление Core 12.11.2026: в репозитории поставлен сервер 0.1.4 с шестью
Java-метриками, универсальным анализом Java/Python, выбором адаптера по пути
и изоляцией ошибок файлов. get_symbol_context возвращает зафиксированный исходник,
путь, SHA, язык, строки и AST-контекст; старые инструменты сохранены.
Сборка и отдельные Java/Python/MCP-проверки описаны в основном
README. Ниже сохранён исторический отчёт LLM-этапа от 11.11; его receipts и
установленная вне репозитория копия плагина не обновлялись этим изменением.

Дата: 11.11.2026. Ветка `codex/llm-workflow`, основа `feature/python ec6a3ed`.
Реализована только зона Java / LLM Engineer. Core, Java/Python-анализаторы,
MCP Java API, существующий JAR и Maven-конфигурация не изменены.

Установленная копия плагина совпадает с файлами `plugin/`. Домашний
`~/.codeclarity/repo-root.txt` настроен на текущий проект (создан при отсутствии
прежней настройки). Запуск установленного JAR без `--repo-root` проверен:
initialize и discovery всех шести Tools прошли с этой постоянной конфигурацией.

| Задача | Сделано | Что остаётся |
|---|---|---|
| LLM-01 | Плагин 0.2.0 локально установлен и включён; Codex CLI обнаружил четыре Skills и реальные MCP Tools | GUI desktop отдельно не проверялся |
| LLM-02 | Оркестратор, immutable independent/main artifacts, coverage, NO_CHANGES/INCOMPLETE, JSON/Markdown; реальный смешанный запуск | Полное шестиметрическое ревью после поставки Core/Python |
| LLM-03 | Независимое чтение Git snapshots до метрик, evidence, стабильные IDs, source ranges; реальные замечания Java/Python и пустой результат на хорошем коде | Более широкая статистическая оценка качества после демо |
| LLM-04 | Сохранение реальных before/after/delta, SUPPORTED/UNRELATED/INSUFFICIENT_DATA, честные пропуски и dedup/origin IDs | Недостающие измерения поставляют Task 01/02 |
| LLM-05 | Skill, предложенный контракт истории/feedback, оба offline synthetic исхода | Реальные history Tools, persistence/replay/provenance подтверждает Task 02; не имитировались |
| LLM-06 | 6 forward Evals, 4 реальных MCP protocol cases, реальный Codex mixed review, 25 invariant/evaluator tests и ID self-test | Live history E2E и повтор после нового JAR |
| LLM-07 | 6 редактируемых слайдов, notes, PNG, mixed demo и backup runbook | Совместная репетиция и согласование финального интегрированного состояния с командой |

## Доказательства

- [Real JAR protocol baseline](../evals/results/protocol-baseline.json): четыре
  случая PASS, реальные discovery/измерения; это не проверка поведения модели.
- [Forward agent evaluation](../evals/results/agent-forward.json): шесть случаев
  PASS, исходные/итоговые Findings, точные численные объекты и синтетические
  кандидаты. Ограничения ослепления оценки указаны в самом файле; историю нельзя
  считать полностью blinded тестом или реальной persistence-проверкой.
- [Installed-plugin Codex run](../evals/results/codex-live.json): PASS проверки
  исполнения, 8 реальных mcp_tool_call; frozen artifact находится до начала
  analyze-вызовов. JSONL hash и ссылки на исходные локальные артефакты сохранены.

Последний запуск использовал установленный `codeclarity@codeclarity-local`
0.2.0 и Codex CLI `0.167.0-alpha.3.2`. База:
`bae43736e7b26f9f89be0296343e4a58a45d1c4a`, head:
`39e04aad95efdc92fc0cf9f42c634fe56953adc4`. Найдены две проблемы: вложенные
проверки Java (`SUPPORTED`) и неясные имена Python (`UNRELATED`). Реальные
Java CC: 1 → 7, CogC: 0 → 21. Python-сигнатуры Core не сопоставил, поэтому
дельта не подставлялась. Все 6 возвращённых сравнений сохранены без изменения.

**PASS проверки сценария не равен PASS читаемости.** Итог самого ревью —
INCOMPLETE: структурные метрики отсутствуют, Python CogC UNSUPPORTED.
History — UNAVAILABLE. Синтетические RULE_SUGGESTED / NO_SUGGESTION проверяют
решение Skill без записи/активации. Не заявляется готовность всего MVP.

## Команды повторной проверки

```powershell
python scripts/llm_evals.py self-test
python scripts/llm_artifact_test.py
python plugin/skills/readability-review/scripts/review_ids.py --self-test
python scripts/llm_evals.py protocol --output .codeclarity/protocol-new
python scripts/llm_demo.py --output .codeclarity/demo-new
python scripts/llm_codex_probe.py --repo .codeclarity/demo-new/repo --output .codeclarity/live-new --mode review --temporary-repo-config
python scripts/llm_codex_evidence.py --run .codeclarity/live-new --output evals/results/codex-live-new.json
```

Протокольные/CLI проверки требуют одного пользователя ОС для Git fixture и MCP;
некоторые Windows sandbox-профили не дают Java читать Git root. Инструкция и
диагностика — [llm-setup.md](llm-setup.md). Probe восстанавливает домашний
repo-root.txt после завершения; параллельное изменение не затирается.

Официальный skill quick_validate.py был запущен, но PyYAML в доступных Python
runtime отсутствует. Фактическая загрузка четырёх Skills Codex проверена.
Опциональный пакет jsonschema также отсутствует: работают документированные
операционные проверки артефактов, а не полная реализация JSON Schema validator.
`mvn clean package` не запускался: сборка/поставка Core остаётся в Task 02;
интеграция проверялась на существующем JAR с зафиксированным SHA256.

Локальная ветка создана; коммиты, push и PR этой работой не выполнялись.
