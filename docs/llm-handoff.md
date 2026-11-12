# Task 03 — границы ответственности и передача команде

Обновление Core 12.11.2026: сервер 0.1.7 вычисляет шесть Java-метрик и предоставляет
единые get_changes/analyze_changes/get_symbol_context для Java/Python с выбором
адаптера по пути и изоляцией ошибок отдельных файлов. Определения и ограничения — в основном
README. Описание и результаты LLM-работ ниже относятся к исходной поставке;
новые LLM-запуски и согласование команды этим обновлением не подтверждаются.
JSON-память реализована через get_review_history/update_review_history с атомарной
записью, повтором без дублей и подтверждениями через явную локальную CLI-команду.
Кандидаты сохраняются отдельно через propose_rule_candidate: только PROPOSED,
не менее трёх разных повторений и двух текущих внешне подтверждённых FIXED.
Повтор запроса не создаёт новое предложение и не активирует правило.
Исправления Windows и границы проверки — в [отчёте](java-core-fixes.md).
Минимальные get_symbol_definition/find_symbol_references работают через общий
LSP-интерфейс и отдельно настроенный JDT LS. Их область — WORKTREE, не Git SHA;
таймаут/ошибка LSP не блокирует метрики. Импорт Maven/Gradle отключён (P1).

Ветка: `codex/llm-workflow`, основа `feature/python ec6a3ed`.
Состав работы: plugin packaging, четыре Skills, AI review contracts,
артефакты/Markdown, шесть Evals, демо и презентация.

## Разделение файлов

| Владелец | Область |
|---|---|
| Python Developer (Task 01) | Python Analyzer, шесть Python-метрик, зависимости, Pyright и Python analyzer tests |
| Java Core Developer (Task 02) | `src/main/**`, общие модели/сравнения, Java-метрики, MCP Tools, JSON storage/feedback, JAR, LSP |
| Java / LLM Engineer (Task 03) | `plugin/skills/**`, manifest/config packaging, `plugin/contracts/**`, `plugin/scripts/**`, `scripts/llm_*`, `evals/**`, `docs/llm-*`, demo/presentation |

Java/Python-файлы в `evals/fixtures` — только входы LLM Evals, не альтернативные
анализаторы и не реализация Python-задач. Существующий JAR используется как
входной артефакт и не пересобирается/подменяется этим изменением. Существующие
MCP Tools и core.model.Finding сохранены.

## Предлагаемый контракт для Core

Статус — **PENDING_TEAM_REVIEW**: это конкретное предложение для согласования,
не утверждение, что коллеги его уже приняли.

- [Finding и полный отчёт](../plugin/contracts/review.schema.json).
- [History/feedback/ruleCandidate](../plugin/contracts/history.schema.json).
- [Текущие и целевые MCP-вызовы](../plugin/contracts/mcp-compatibility.md).

Новое AI Finding содержит review/finding IDs, snapshot, source/category,
location, evidence, description/recommendation, metricRelation и
`reviewStatus: PENDING_FEEDBACK`. Это другой контракт, чем существующий PMD
`Finding(rule,line,column,message)`; заменять его без адаптации не требуется.
Если при объединении меняется ID, `originFindingIds` сохраняет связь с
неизменным независимым артефактом. Модель не может утверждать человеческий FIXED.

Review ID детерминирован по repoRoot + base/head/snapshot + languages/paths;
Finding ID — по review/snapshot/category/location/evidence. Helper не пишет
историю. Для строгой изоляции между копиями одного репозитория в дальнейшем
можно согласовать repoId: текущая версия намеренно использует явный repoRoot.

Стороны численных метрик из текущего Core сохраняются без изменения.
Внутри definition версии уже входят в analyzer/algorithm. Для пропущенного ID
в отчёте нет вымышленного MetricValue/версии; есть skip и ячейка MISSING в Markdown.
Неизвестные counts = null, что требует INCOMPLETE. Время не участвует в ID.

## Что передать нам от коллег

1. Новый JAR, точную команду запуска и версии; шесть метрик обоих языков,
   семантику алгоритмов и примеры результатов. В 0.1.2 шесть Java-метрик уже есть;
   для Python пока есть CC и явный UNSUPPORTED для CogC.
2. Реальные discovery schemas универсальных Tools, если они будут добавлены.
   В 0.1.4 доступны три основных универсальных инструмента, прежний inspect_symbol_ast
   и шесть языковых инструментов для совместимости.
3. `get_review_history`, `append_review_result`, `record_feedback`,
   `propose_rule_candidate` или документированные эквиваленты. Core должен
   обеспечить атомарность, конкуренцию, идемпотентность и проверку provenance
   feedback; декларация модели `confirmedBy` не является подтверждением.
4. Python-примеры с ожидаемыми шестью метриками и известными ограничениями.
   Тестовые LLM-примеры здесь не заменяют проверку Python-анализатора.

После передачи: заменить JAR штатным процессом Core, повторить протокол/Evals,
проверить реальную запись/read-back/replay истории и новую/повторную заявку
правила, обновить фактический статус слайдов, провести совместную репетицию.
До появления history Tools обычный review возвращает UNAVAILABLE для истории;
подмена прямой записью файла запрещена. Подготовленная синтетическая история
проверяет только решение Skill и не доказывает безопасность/работоспособность БД.

## Готовность

Реализованы четыре Skills и артефакты, документирована упаковка и запуск;
существующий сервер проверяется реальными MCP-клиентами. Полный критерий Task 03
зависит от Core/метрик/history, доступа Codex к MCP и совместной репетиции.
Фактические результаты запусков находятся в `evals/results/`, а не выводятся из
наличия README или успешной компиляции. Совместная репетиция и согласование с
другими людьми не объявляются выполненными автоматически.
Подробная таблица LLM-01…LLM-07 и команды проверки: [llm-status.md](llm-status.md).
