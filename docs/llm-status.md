# CodeClarity — объединённая версия 0.4.0

Дата: 12.11.2026. Ветка `codex/llm-workflow`. Объединены Python `dc9d957`,
LLM workflow `8f612ac` и Java Core с исправлениями `afe8b08`.
Пакет плагина — **0.4.0**, сервер — **0.1.7**.

В общей версии сохранены шесть Python-метрик, qualified matching и launcher;
добавлены шесть Java-метрик, универсальный MCP, committed source context,
coverage изменённых строк, JSON-история и сохранение PROPOSED-кандидатов.
Неоднозначное сопоставление не получает выдуманную численную delta.
История принимает внешние решения оператора отдельно от MCP review payload.

Чистая Maven-компиляция и упаковка выполнены на JDK 21. Общий набор —
**20/20 PASS**, Maven workflow-checks — **BUILD SUCCESS** на том же JAR.
Первый прогон выявил 45-секундный лимит тестового клиента на партии из 50 Python
файлов; только этот тест получил 120 секунд, после чего весь набор прошёл.
[Сборка, проверки и SHA-256](../evals/results/unified-integration-build.json).
CP1251 LSP smoke также прошёл без глобального UTF-8 режима.

Первый новый Codex-сеанс подтвердил 24 сравнения, 4 группы, полное покрытие и
WARN с двумя находками, сохранив основной отчёт после отказа approval policy
в записи истории. [Этот отказ](../evals/results/codex-unified-approval-denied.json)
сохранён отдельно. [Повтор полного процесса](../evals/results/codex-unified-integration.json)
завершился **PASS**: 13 настоящих MCP-вызовов, четыре сущности обоих языков,
24 сравнения, два обоснованных замечания и итоговый **WARN**. Полная Draft 2020-12
schema validation прошла; freeze предшествует первому numeric analyze.

История сохранена через native update_review_history и прочитана обратно.
Два независимых перезапуска JVM и повтор того же reviewId подтвердили revision 1,
неизменные bytes/mtime, один review, две DETECTED-находки и ноль FIXED/feedback.
Rule Discovery — **NO_SUGGESTION**: внешних подтверждений нет.
Запись разрешалась только в новом одноразовом fixture через process-local
настройку одного update_review_history. Глобальная политика не изменялась.
Дополнительно прошли **33 artifact** и **13 evaluator** регрессий; проверка
artifact-link отделяет ссылку discovery.json от семантики решения и проверяет оба.

Установленная копия плагина этим слиянием не обновляется.

На Windows настоящий JDT LS остаётся NOT_RUN; проверены протокол и корректная
деградация без него. Новый Codex-тест использовал репозиторные Skills и явный
MCP-сервер, поэтому его результат не является проверкой installed plugin cache.

## Исторический результат Python-интеграции 0.3.2

Дата: 12.11.2026. Ветка `codex/llm-workflow`. Python-ветка
`feature/python-metrics-integration` (`dc9d957`) слита merge-коммитом `a922e40`.
Плагин **0.3.2** установлен локально; serverInfo JAR остаётся **0.1.1**.
Исходники Core, анализаторы и JAR приняты без дополнительных изменений нашей стороны.
Их SHA/алгоритмы не следует определять по одной версии serverInfo.

## Результат

| Часть | Фактическое состояние |
|---|---|
| Python | Все шесть метрик через выбранный Python с complexipy 8.3.0 |
| Matching | Точные Core-группы и диапазоны сохранены в entityMatches; переименование параметров не разрывает пару |
| Independent Review | До метрик; покрытие в SNAPSHOT_ENTITY, обе версии читаются отдельно |
| Итоговое покрытие | MATCH_GROUP из Core; frozen independent не переписывается при другом количестве групп |
| Python-only Codex demo | PASS: 2 файла, 4/4 source occurrences, 2/2 группы, 12 сравнений, 0 обоснованных замечаний |
| Naming forward Eval | WARN: 1 opaque_names / UNRELATED, 6 доступных сравнений; малые числа не отменяют замечание |
| History | UNAVAILABLE в production; два синтетических исхода Skill проверены без persistence |
| Java / LSP | Java по-прежнему CC/CogC, четыре метрики и LSP ожидают Core-участника |
| Презентация | Обновлена на фактический Python PASS и отдельный Naming WARN; совместная репетиция не проведена |

PASS здесь относится к выбранному Python scope и политике ревью, не означает идеальный
код или готовность всех частей MVP. Смешанный scope с отсутствующими Java-метриками
остаётся INCOMPLETE. Пустой Finding[] на улучшенном коде допустим.

## Доказательства

- [Сборка и 8 наборов Core/Python/Java/MCP-проверок](../evals/results/python-integration-build.json):
  свежий bundled build, JDK 21, Python 3.13.2; 30 unit-тестов и 20 эталонов × 6 значений,
  matching, границы партий, отказы зависимостей и два эксперимента — PASSED.
- [Четыре LLM protocol-сценария](../evals/results/protocol-python-integration.json):
  реальный поставленный JAR, точные новые пары/измерения; это не доказательство работы модели.
- [Naming + synthetic history forward test](../evals/results/agent-python-integration-summary.json):
  свежий агент, реальный source-built target-JAR, WARN и два offline исхода. Уровень
  проверки явно отличается от установленного плагина, исходные артефакты и хеши сохранены.
- [Установленный плагин → реальный Codex](../evals/results/codex-python-integration.json):
  completed exit 0, **6 настоящих MCP-вызовов**, freeze до начала analyze, полный JSON Schema
  и операционная проверка PASS. Итог самого ревью — PASS; история — UNAVAILABLE.
- [Четыре проверки launcher](../evals/results/python-launcher.json): реальная файловая
  настройка без внешнего env, приоритет явного env, корректная деградация без зависимости,
  ошибка отсутствующего JAR; STDIO и завершение дочерних процессов проверены.
- [Контролируемая деградация Codex](../evals/results/codex-python-degraded.json): более ранний
  запуск без переданного Python дал INCOMPLETE с CogC ERROR, сохранив остальные пять
  метрик. Это отдельный результат, не финальный успешный Python-прогон.

Поставленный JAR: `3c4bc878473fe264accf50224a4066060bad8832a318901a4bee79882841da69`.
В live-демо база `a9b7fb2f15e1f72f2ca15852920c7c59337abbcc`, head
`4dcbe93bd635a27d51f6eab19d1870955f4050e6`. Наблюдались настоящие значения
shipping_fee CogC 12 → 4, nesting 4 → 1; remaining сохранил все шесть значений.
Это измерения конкретных версионированных алгоритмов, не универсальная оценка качества.

## Runtime и воспроизведение

Проверенный Codex CLI 0.167.0-alpha.3.2 не принимает env_vars в plugin mcp.json
и фильтрует часть унаследованного окружения. Пакет использует небольшой Java source-file
launcher, которому нужен JDK 21+. Он передаёт selector Python дочернему Core явно:
CODECLARITY_PYTHON, когда переменная доступна, иначе ~/.codeclarity/python-path.txt.
Настройка файла подготовлена для локального .venv; repo-root.txt восстановлен на текущий проект.
Нового вычислителя метрик, API или отдельного backend не добавлялось.

Повторная установка/конфигурация: [llm-setup.md](llm-setup.md).
Демо: [llm-demo.md](llm-demo.md). Границы задач: [llm-handoff.md](llm-handoff.md).
Презентация: [CodeClarity_Python_Integration.pptx](presentation/output/CodeClarity_Python_Integration.pptx).

Выполнены **24 artifact + 11 evaluator + 4 launcher = 39 автоматических проверок**,
ID self-test, штатная валидация четырёх Skills и полная Draft 2020-12 валидация
актуальных отчётов. Закреплённые dev-инструменты находятся в requirements-llm-dev.txt.
Maven backend отдельно не запускался; проверен документированный bundled backend.
Один live-прогон не доказывает детерминированность модели.

## Оставшиеся зависимости

Java-метрики, универсальные/history Tools, атомарность/idempotence хранения,
авторизация настоящего feedback и LSP остаются в Task 02. Новые AI-предложения
не активируются автоматически. Подготовленная история не является подтверждениями
реальных пользователей. Совместная репетиция и согласование с людьми не имитировались.

Результаты 0.2.0 в agent-forward.json, codex-live.json и protocol-baseline.json
сохранены неизменными как исторический baseline. Текущая интеграция записана в новые файлы.
Публикация ветки/PR в эту работу не включалась: изменения остаются локальными.
