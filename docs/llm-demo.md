# Демонстрация CodeClarity

Плагин 0.3.2 использует интегрированный Python-анализатор с шестью метриками.
Подготовка Python/плагина описана в [llm-setup.md](llm-setup.md).
Фактические результаты текущих прогонов находятся в [llm-status.md](llm-status.md).

## Python: структура и имена

Из корня проекта, с выбранным Python-окружением:

```powershell
$codeclarityPython = (Resolve-Path '.venv/Scripts/python.exe').Path
$env:CODECLARITY_PYTHON = $codeclarityPython
New-Item -ItemType Directory -Force "$env:USERPROFILE\.codeclarity" | Out-Null
Set-Content -LiteralPath "$env:USERPROFILE\.codeclarity\python-path.txt" -Value $codeclarityPython -Encoding utf8NoBOM
& $codeclarityPython scripts/llm_demo.py --source python-experiments --output .codeclarity/python-demo-new
```

Скрипт переиспользует before/after-исходники из
`experiments/python_readability/structure` и `naming`, создаёт отдельный Git
fixture с двумя коммитами и `manifest.json` со scope/SHA. Новых вычислителей метрик
или вариантов Python-анализатора в демонстрации нет.
Java launcher плагина читает `python-path.txt` при старте и передаёт выбранный
интерпретатор Core. После изменения selector перезапустите MCP-сервер/сеанс
плагина; после обновления пакета откройте новый локальный чат.

Первый пример меняет вложенные проверки на ранние выходы. Второй улучшает имена
при неизменных метриках. Их реальные измерения и ограниченный набор проверок
поведения описаны в [материалах Python-разработчика](../experiments/python_readability/README.md).
Авторские пояснения этих материалов не являются независимым AI-ревью.

Запрос для нового локального чата:

> Используй CodeClarity readability-review для Python-изменений main..HEAD
> в подготовленном репозитории. Сначала прочитай Git-исходники и зафиксируй
> независимые Findings, затем вызови реальные MCP-метрики. Верни JSON/Markdown,
> покрытие, доказательства и пропуски. Исходники не меняй.

До freeze не передавайте независимому этапу manifest с ожидаемыми метриками,
сохранённые результаты или авторские ожидаемые выводы. Его вход — scope,
Git-исходники/diff и необходимый AST-контекст. Пустой Finding[] на улучшенном
коде допустим; демонстрация не должна требовать выдуманного замечания.

Полный Python-only запуск через установленный Codex CLI:

```powershell
& $codeclarityPython scripts/llm_codex_probe.py --repo .codeclarity/python-demo-new/repo --output .codeclarity/python-live-new --mode review --languages python --python $codeclarityPython --temporary-repo-config
& $codeclarityPython scripts/llm_codex_evidence.py --run .codeclarity/python-live-new --output evals/results/codex-python-new.json --languages python
```

Порядок: list changes → Git/AST → independent freeze → analyze → correlation →
основной отчёт → history. Python-only ревью с полным покрытием и шестью доступными
метриками может вернуть PASS или WARN. History Tools пока отсутствуют, поэтому
машинный статус истории — UNAVAILABLE; это само по себе не требует INCOMPLETE
для основного отчёта. Ошибка зависимости, метрики или обязательного этапа требует
INCOMPLETE с сохранением остальных результатов.

## Смешанный пример и неполнота Java

Старый LLM fixture остаётся доступным:

```powershell
& $codeclarityPython scripts/llm_demo.py --output .codeclarity/mixed-demo-new
& $codeclarityPython scripts/llm_codex_probe.py --repo .codeclarity/mixed-demo-new/repo --output .codeclarity/mixed-live-new --mode review --python $codeclarityPython --temporary-repo-config
```

Он показывает вложенные проверки Java и ухудшение Python-имён. Python теперь
возвращает шесть метрик; изменение имён параметров может сохранять MATCHED и delta.
Java пока возвращает CC/CogC, поэтому смешанное ревью затронутых Java-методов
остаётся INCOMPLETE из-за четырёх отсутствующих Java-метрик.
Сигнатуры/диапазоны сторон берутся из `files[].matches`; покрытие считают по
группам Core, не по объединению старых и новых строк signature.

Для проверки именования при низких измерениях также доступен отдельный
`scripts/llm_evals.py prepare --scenario python-naming --output <новый-каталог>`.
Ожидаемые ответы evaluator не следует передавать independent-review.

## Rule Discovery

Тестовые истории `evals/fixtures/history/sufficient.json` и `insufficient.json`
содержат подготовленные **синтетические** находки и подтверждения.
Для offline показа явно попросите rule-discovery оценить supplied synthetic
fixture без persistence. Выход — `executionLevel: SYNTHETIC_SKILL_EVAL`,
`synthetic: true`, `decision: RULE_SUGGESTED` с PROPOSED-кандидатом либо
`decision: NO_SUGGESTION` и пустым пользовательским текстом.
Это решение Skill, не сохранение в Core и не реальные исправления пользователей.

Live JSON History станет доступна после поставки Tools участником 2:
append → read-back → повтор reviewId без дубля → подтверждённые тестовые события →
propose → повтор без нового предложения. Пока прямой записью файла истории
интеграция не имитируется.

## Резерв и репетиция

Презентация и PNG находятся в `docs/presentation/`. Для резерва используйте
сохранённые реальные receipts/отчёты с точным уровнем проверки и SHA.
Исторические результаты версии 0.2.0 не отражают новые Python-метрики и matching;
они остаются неизменными baseline-файлами. Новые запуски пишутся отдельно.
Протокольный тест нельзя выдавать за Codex E2E, offline history — за persistence.

Перед общим показом проверить: repo-root, выбранный Python и версию complexipy,
четыре Skills/Tools, совпадение SHA, freeze до метрик, реальные source ranges,
единицы покрытия, отсутствие вымышленных чисел и честную полноту.
Совместная репетиция с командой пока не проведена.
