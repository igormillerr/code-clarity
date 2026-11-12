# Task 03 — границы ответственности и интеграция

Ветка: `codex/llm-workflow`. Первоначальная LLM-часть основана на
`feature/python ec6a3ed`; Python-интеграция `dc9d957` принята merge-коммитом
`a922e40`. Пакет плагина — `0.3.2`.

## Разделение файлов

| Владелец | Область |
|---|---|
| Python Developer (Task 01) | Python Analyzer, шесть Python-метрик, зависимости, Pyright и analyzer tests |
| Java Core Developer (Task 02) | Общие модели/сравнения, Java-метрики, MCP Tools, JSON storage/feedback, JAR, LSP |
| Java / LLM Engineer (Task 03) | Plugin packaging, `plugin/skills/**`, `plugin/contracts/**`, `plugin/scripts/**`, `scripts/llm_*`, `evals/**`, LLM docs, демо и презентация |

Из Python-ветки приняты её анализатор, JAR, тесты и изменения общего matching
без дополнительной переработки предметной логики. Продолжение изменений общих
Core-файлов нужно координировать с участником 2. Java/Python-файлы в `evals/fixtures`
служат входами LLM Evals; они не заменяют анализаторы или их unit-тесты.
Имена шести существующих языковых MCP Tools и диагностический `core.model.Finding`
сохранены.

## Получено от Python-разработчика

- Все шесть численных Python-метрик; CogC через строго `complexipy==8.3.0`.
- [Спецификация семантики](PYTHON_METRICS_SPEC.md), эталоны и единый `scripts/check.py`.
- Сопоставление Python по qualified name без параметров; изменение параметров
  может сохранить пару и корректные delta.
- `files[].matches` с исходными сущностями и диапазонами обеих версий.
- [Два демонстрационных эксперимента](../experiments/python_readability/README.md)
  с проверкой поведения и фактическими MCP-измерениями.

Python worker использует выбранный `CODECLARITY_PYTHON`; версия зависимости
должна быть установлена в этот интерпретатор. Ошибка CogC сохраняет остальные
пять измерений. `AnalysisResult.complete` относится к AST/entities, а доступность
метрик определяется их статусами и warnings. Текстовые интерпретации экспериментов
не следует выдавать за результаты независимого AI-review.

Java launcher `plugin/scripts/LaunchMcp.java` относится к упаковке LLM-части.
Он выбирает переданную переменную `CODECLARITY_PYTHON` или домашний
`~/.codeclarity/python-path.txt` и явно задаёт selector дочернему Core-процессу.
Без selector сохраняется стандартный Python из PATH. Файловый selector
предусмотрен для хоста, который фильтрует пользовательские переменные;
алгоритмы и поставленный JAR не перерабатываются. Настройка файла и порядок приоритетов — в
[llm-setup.md](llm-setup.md).

## Контракты LLM → Core

Статус предложений истории — **PENDING_TEAM_REVIEW**; интеграция Python сама по
себе не означает согласование участником 2 модели хранения и feedback.

- [Finding и полный отчёт](../plugin/contracts/review.schema.json).
- [History/feedback/ruleCandidate](../plugin/contracts/history.schema.json).
- [Текущие и целевые MCP-вызовы](../plugin/contracts/mcp-compatibility.md).

AI Finding содержит review/finding IDs, snapshot, source/category, location,
evidence, description/recommendation, metricRelation и
`reviewStatus: PENDING_FEEDBACK`. Это отдельный контракт от PMD-диагностики
`Finding(rule,line,column,message)`. При объединении `originFindingIds` сохраняет
связь с неизменным независимым артефактом. Модель не подтверждает собственный FIXED.

Review ID детерминирован по repoRoot + base/head/snapshot + languages/paths;
Finding ID — по review/snapshot/category/location/evidence. Время не участвует в ID.
Текущий repoRoot намеренно различает локальные копии проекта; переход к отдельному
repoId требует отдельного согласования.

Стороны метрик и delta сохраняются ровно из Core, с analyzer/algorithm definitions.
Пропущенный ID не получает вымышленного MetricValue или версии: его отсутствие
отмечается skip и MISSING в Markdown. Core matching сохраняется в `entityMatches`,
без повторной реализации сопоставления в LLM.

Независимое покрытие использует `SNAPSHOT_ENTITY`: рассматриваются исходные
сущности обеих версий. Итоговое покрытие использует `MATCH_GROUP`: группы Core
могут объединять разные before/after-сигнатуры. Различие counts не требует
перезаписи frozen независимого результата. Для старого ответа без matches
допускается явно обозначенный `LEGACY_METRIC_ENTITY`; неизвестные counts остаются
null и требуют INCOMPLETE.

## Что ещё нужно от Java Core

1. Четыре структурные Java-метрики и их определения. Сейчас Java возвращает
   CC/CogC; Python-only scope уже не должен автоматически считаться неполным.
2. Discovery schemas универсальных Tools, если они появятся. Совместимость с
   шестью текущими языковыми Tools сохраняется.
3. `get_review_history`, `append_review_result`, `record_feedback`,
   `propose_rule_candidate` или документированные эквиваленты: атомарность,
   конкурентная запись, идемпотентность и проверка provenance feedback остаются
   обязанностью Core. Строка модели `confirmedBy` не является подтверждением.
4. Опциональный LSP-контекст. Его отсутствие не блокирует полный AST/metric review.

Без history Tools обычное ревью записывает машинный UNAVAILABLE и сохраняет
основной отчёт. Прямой записи `.codeclarity/review-history.json` в Skills нет.
Подготовленная синтетическая история проверяет решение Skill, не persistence.

После поставки Core: повторить протокол/Evals, проверить реальные append/read-back,
повторный reviewId без дублей и новую/повторную заявку правила. Основной review
и pre-discovery history payload остаются неизменными; исход discovery хранится
отдельно, а итоговый display report создаётся новым артефактом.

## Готовность и доказательства

Техническая приёмка Python-ветки выполнена отдельно от LLM-интеграции. Текущие
проверки плагина, модели и артефактов перечислены в [llm-status.md](llm-status.md).
Новые результаты не перезаписывают исторические `evals/results/*.json` от версии
0.2.0. Полнота ревью определяется данными конкретного запуска, а не старым
baseline или одним serverInfo.

Для полного Task 03 остаются интеграция history/Core и совместная репетиция.
Согласование с людьми и репетиция не объявляются выполненными автоматически.
