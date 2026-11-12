# Презентация CodeClarity

Шесть редактируемых слайдов: [PowerPoint](output/CodeClarity_Python_Integration.pptx). Текст и заметки докладчика: [slides.md](slides.md). PNG каждого финального слайда находятся в [previews](previews/). Предыдущие `CodeClarity_MVP_reviewed.pptx` и `CodeClarity_MVP_final.pptx` сохранены как исторические версии предыдущего среза.

Текущая интеграция: Python `dc9d957` через merge `a922e40`, пакет 0.3.2. Python возвращает все шесть метрик, включая Cognitive Complexity через complexipy 8.3.0. Таблица показывает реальные before/after структурного эксперимента `shipping_fee`. Пример `remaining` показывает изменения имён при неизменных шести измерениях. Измерения повторно подтверждены свежими `target/experiments` и восемью наборами Core-проверок.

Последний слайд различает два уровня: завершённый **Codex CLI через установленный плагин** дал `PASS` для двух улучшенных Python-файлов без обоснованных находок; **отдельный forward Eval с реальным source-built JAR** дал `WARN` с одной `opaque_names` находкой `UNRELATED`. Первый содержит шесть реальных MCP-вызовов и 12 точных сравнений, второй сохраняет замечание об именах при низких CC/CogC. Подтверждения: [codex-python-integration.json](../../evals/results/codex-python-integration.json) и [agent-python-integration-summary.json](../../evals/results/agent-python-integration-summary.json).

`PASS` относится к проверенному Python scope и не доказывает идеальное качество или готовность всего MVP. История `UNAVAILABLE`, четыре структурных Java-метрики и JSON persistence остаются зависимостью от Core. LSP недоступен. После поставки Core обновите фактическое состояние перед общим показом.

## Повторная сборка

Нужен bundled Node.js, пакет `@oai/artifact-tool` и runtime Python из `load_workspace_dependencies`. Дополнительные пакеты не устанавливаются. Пример PowerShell:

```powershell
$env:CODECLARITY_NODE_MODULES = '<bundled node_modules>'
$env:CODECLARITY_PRESENTATIONS_SKILL = '<presentations SKILL.md directory>'
$env:CODECLARITY_RUNTIME_PYTHON = '<bundled python.exe>'
$env:CODECLARITY_DECK_FILENAME = 'CodeClarity_MVP_revised.pptx'
& '<bundled node.exe>' .\docs\presentation\build.mjs
```

Перед первым create/edit используйте маркер операции из Presentations skill. Сборщик сохраняет промежуточные файлы и проверки в игнорируемом `.build/`, экспортирует шесть PNG и создаёт отдельный итоговый PPTX. Итоговое имя должно быть новым: финализатор не перезаписывает существующий файл.

## Репетиция и резервный показ

Совместная репетиция пока не проведена. Перед демонстрацией участники проверяют поставленные анализаторы и JSON Tools, затем выполняют общий [demo runbook](../llm-demo.md).

Если live-запуск нестабилен, используйте:

1. PNG слайдов для объяснения продукта.
2. Сохранённый фактический протокол MCP/Codex, с указанием даты, SHA и статуса.
3. Отчёт реального запуска, включая `INCOMPLETE`, если обязательные зависимости отсутствовали.
4. Отдельно помеченную синтетическую историю для объяснения Rule Discovery.

Фактический одиночный Python Codex CLI прогон завершён, совместная репетиция и запись видео пока не проведены. Обе ветви Rule Discovery прошли на явно синтетической истории, но это не доказывает запись JSON через Core. Не представляйте эти assessments или протокольный smoke-тест как полный MVP E2E.
