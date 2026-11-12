# CodeClarity — передача объединённого MVP

Ветка: `codex/llm-workflow`. Пакет 0.4.0, сервер 0.1.7. Источники:
Python `dc9d957`, LLM workflow `8f612ac`, Java Core и исправления `afe8b08`.

## Границы ответственности

| Участник | Область |
|---|---|
| Python Developer | Python worker, шесть метрик, complexipy 8.3.0, алгоритмы и эталоны |
| Java Core Developer | Git snapshots, маршрутизация, matching, Java-метрики, MCP, JSON storage/feedback, LSP |
| Java / LLM Engineer | Plugin packaging, четыре Skills, отчёт, correlation, Rule Discovery, Evals и демонстрация |

Объединённая версия сохраняет обе реализации; изменения общего контракта
сопровождаются тестами. Приёмка продукта описана в [статусе](llm-status.md).

## Переданные возможности

- По шесть Java/Python-метрик с определениями алгоритмов и статусами доступности.
- Смешанные get_changes/analyze_changes и committed get_symbol_context.
- Python matchingKey без параметров; сохранение files[].matches в entityMatches.
- matchingAmbiguous и matchingWarning: неоднозначность и неподтверждённую
  идентичность нельзя превращать в уверенную пару или delta.
- coverage.base/head: изменённые строки вне поддерживаемых сущностей видны явно.
- get_review_history/update_review_history: immutable reviews, категории,
  производная статистика и атомарная идемпотентная запись.
- propose_rule_candidate: только PROPOSED, не менее трёх source/snapshot
  occurrences и двух последних операторских FIXED разных повторений.
- Необязательные WORKTREE definition/references через JDT LS; отсутствие LSP
  не убирает результаты AST/метрик. Контекст WORKTREE не приписывается другому SHA.

## Отчёт и порядок работы

[review.schema.json](../plugin/contracts/review.schema.json) описывает AI-отчёт.
Это отдельная модель от PMD Finding(rule,line,column,message).
Независимый анализ читает оба Git-снимка до измерений и фиксируется неизменным
артефактом. Его покрытие — SNAPSHOT_ENTITY; итоговое — MATCH_GROUP из Core.
Различие этих counts не требует переписывать независимый результат.

Стороны метрик, определения и delta сохраняются из Core. Недоступность или
неподтверждённая идентичность остаются явными; значения не восстанавливаются
вычитанием в Skill. Основной отчёт сохраняется до discovery.

Для истории создаётся стабильный review.history-input.json с NOT_RUN и теми же
reviewId/findingId. update_review_history принимает review/categories, но не
feedback или клиентские счётчики. Исход discovery хранится отдельно; итоговый
report.final.json/.md создаётся новым артефактом. Replay не обновляет immutable
находки и не удваивает статистику.

FIXED/REJECTED записываются только по явному решению оператора через локальную
CLI-команду с автором и evidence. Исчезновение диагностики или модельное
confirmed:true не устанавливают FIXED. Предложения правил не активируются.
Кандидаты ссылаются на известные findings/feedback и проверяются Core.

Точные входы и ограничения:
[MCP compatibility](../plugin/contracts/mcp-compatibility.md),
[history update](../plugin/contracts/history-update.schema.json),
[persistent history](../plugin/contracts/review-history.schema.json),
[rule candidate](../plugin/contracts/rule-candidate.schema.json).

## Runtime и проверка

Нужны JDK 21+, Git и Python с requirements-llm-dev.txt. Плагин использует
LaunchMcp.java и передаёт выбранный Python дочернему JAR; настройки описаны в
[llm-setup.md](llm-setup.md). Maven verify собирает и проверяет общую версию.
JAR в plugin/server должен совпадать с проверенным target JAR по SHA-256.

Исторические receipts 0.2.0/0.3.2 и самостоятельной Java-ветки сохранены.
Новые результаты объединения имеют отдельные имена. Внешнее согласование команды,
реальная Windows JDT LS-навигация и установленный плагин не объявляются
проверенными по одному успешному локальному MCP-тесту.
