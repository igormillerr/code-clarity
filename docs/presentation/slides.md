# CodeClarity: шесть слайдов для демонстрации

Python `dc9d957` интегрирован merge-коммитом `a922e40`, пакет CodeClarity 0.3.2. Все шесть метрик Python доступны, Java пока возвращает только CC/CogC. Последний слайд показывает завершённый установленный Codex CLI прогон и отдельный forward Eval. Ранее экспортированные PPTX сохраняют историческое состояние. Продолжительность: около 4 минут.

## 1. CodeClarity

Читаемость изменений Java и Python. Разработчик получает объяснение проблем до ревью человеком.

Заметки: AI помогает писать код, а команде нужно понять его назначение и стоимость сопровождения. CodeClarity проверяет Git-изменения. Не объявлять весь MVP завершённым на основании существования плагина.

## 2. Имена меняются при одинаковых метриках

Контролируемый пример `experiments/python_readability/naming`. Назначение `remaining`: остаток вместимости после бронирования, `max(capacity - reserved, 0)`.

До:

```python
def remaining(a, b):
    c = a - b
    if c < 0:
        return 0
    return c
```

После:

```python
def remaining(capacity, reserved):
    available = capacity - reserved
    if available < 0:
        return 0
    return available
```

Все шесть измерений до и после равны: CC 2, CogC 1, SLOC 5, nesting 1, parameters 2, returns 2. Нулевые дельты не отменяют содержательное обсуждение имён. `matchingKey` сохраняет соответствие функции при переименовании параметров. Поведение совпало на 20 подготовленных наборах, но общая семантическая эквивалентность не доказана. Сам `python_experiments` не выполняет независимое AI-ревью.

## 3. Порядок проверки

1. Git snapshots: scope, SHA, исходники.
2. Independent Review: находки до текущих метрик.
3. MCP metrics: измерения Core и статусы доступности.
4. Metrics Correlation: связь чисел с наблюдениями.
5. Report: JSON, Markdown, доказательства, вердикт.
6. Rule Discovery: история и кандидат правила.

Локальный Java 21 Core и MCP STDIO. Skills разделяют этапы логически в одном контексте Codex. Python измеряет все шесть метрик через Core, Java пока возвращает CC/CogC. LSP недоступен и не блокирует AST-only сценарий.

## 4. Шесть метрик Python

`shipping_fee`: структурный пример `experiments/python_readability/structure`, фактические значения из свежего `target/experiments`.

| Метрика | Java | Python до / после |
|---|---|---|
| Cyclomatic complexity | PMD | 5 / 5 |
| Cognitive complexity | PMD | 12 / 4 |
| Function SLOC | Ожидает Core | 12 / 10 |
| Max nesting depth | Ожидает Core | 4 / 1 |
| Parameter count | Ожидает Core | 1 / 1 |
| Return count | Ожидает Core | 1 / 5 |

Python Cognitive Complexity вычисляет complexipy 8.3.0, четыре структурные метрики используют AST и исходный текст. Рост return_count с 1 до 5 сам по себе не доказывает дефект. Поведение совпало на 32 подготовленных наборах, что не доказывает общую семантическую эквивалентность. Восемь наборов проверок свежей интеграции прошли на JDK21 и Python3.13.2.

## 5. Rule Discovery

Начальная эвристика: не менее трёх отдельных обнаружений одной категории, не менее двух исправлений с внешним подтверждением, нет эквивалентного предложенного правила.

Результат: кандидат `PROPOSED`, примеры и исключения. Человек принимает решение об активации. Без оснований Skill не выводит предложение.

Заметки: история для показа синтетическая. Числа здесь задают эвристику, а не статистику пользователей. Новый forward Eval прошёл для обеих ветвей: `RULE_SUGGESTED` с кандидатом `PROPOSED` и `NO_SUGGESTION` с пустым сообщением. Эти проверки решения Skill не доказывают persistence через Core. Статический `RESOLVED` не доказывает подтверждённый человеком `FIXED`. Запись истории принадлежит Core. В пакете 0.3.2 history MCP Tools отсутствуют.

## 6. Python: два проверенных сценария

**Установленный плагин 0.3.2, реальный Codex CLI: `PASS`.** Два файла, шесть реальных MCP-вызовов: `list_python_changes`, четыре `inspect_python_function`, `analyze_python_changes`. Независимое ревью рассмотрело 4/4 `SNAPSHOT_ENTITY` до текущих метрик; окончательное покрытие 2/2 `MATCH_GROUP`. Сохранены 12 точных сравнений Core: шесть видов метрик на каждую функцию, обе стороны `AVAILABLE`. Head обоих контролируемых примеров уже улучшен, поэтому обоснованных находок нет. `PASS` относится к выбранному scope и не доказывает идеальное качество кода. История `UNAVAILABLE`, main report и frozen artifact сохранены неизменными.

**Отдельный forward Eval, source-built target JAR: `WARN`.** На регрессии имён в `invoice_totals.py` независимый reviewer сформулировал одну находку `opaque_names`, корреляция сохранила `UNRELATED` при низких CC/CogC. Все шесть пар `COMPARED`, две snapshot-сущности сопоставлены в одну match group. Это отдельный тестовый транспорт, не установленный plugin E2E.

Результаты относятся к разным fixtures. Все проверки артефактов/evaluator/launcher, восемь Core-наборов, четыре Skills и полная JSON Schema прошли. Общая готовность MVP ещё зависит от четырёх Java-метрик и JSON-истории. LSP недоступен, совместная репетиция `NOT_RUN`.

## Основания для утверждений

- `CodeClarity_Agent_Concept_MVP.md`: продуктовые решения, метрики, порядок этапов, история и ADR.
- `CodeClarity_Task_03_Java_LLM_Developer.md`: LLM-01…LLM-07.
- Интеграция Python `dc9d957` через merge `a922e40`; `plugin/plugin.json` 0.3.2.
- Задания участников 1 и 2: границы ответственности за Python, Core, метрики, LSP и историю.
- `experiments/python_readability/README.md`, `target/experiments/run.json`, `target/experiments/summary.md`: контролируемые примеры и свежие измерения.
- `target/checks/report.json`: восемь наборов проверок интеграции, окружение и SHA JAR.
- `evals/results/codex-python-integration.json`: завершённый реальный Codex CLI Python-прогон, вызовы, порядок стадий, метрики и сохранённые артефакты.
- `evals/results/agent-python-integration-summary.json`: отдельный forward Naming Eval и синтетические history assessments.
- `evals/results/codex-live.json` и `agent-forward.json` относятся к предыдущему срезу и не используются как доказательство нового прогона.
