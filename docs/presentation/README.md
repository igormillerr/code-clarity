# Презентация CodeClarity

Шесть редактируемых слайдов: [PowerPoint](output/CodeClarity_MVP_final.pptx). Текст и заметки докладчика: [slides.md](slides.md). PNG каждого финального слайда находятся в [previews](previews/). Предыдущий `CodeClarity_MVP_reviewed.pptx` сохранён как историческая версия до фактического Codex-прогона.

Таблица метрик фиксирует исходную основу `feature/python` на `ec6a3ed`. Последний слайд показывает наблюдаемый LLM-срез: установленный плагин 0.2.0, четыре Skills, восемь реальных MCP-вызовов Codex CLI, две AI-находки и шесть прошедших forward Evals. Четыре Eval сценария используют реальный JAR, два проверяют решение на синтетической истории. Подтверждения: [codex-live.json](../../evals/results/codex-live.json) и [agent-forward.json](../../evals/results/agent-forward.json).

Вердикт фактического запуска `INCOMPLETE`, история `UNAVAILABLE`. Это не утверждение о готовности всех шести метрик, persistence, feedback или полного MVP. После поставки Core/Python обновите фактическое состояние перед общим показом.

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

Фактический одиночный Codex CLI прогон завершён, совместная репетиция и запись видео пока не проведены. Синтетические history Evals не доказывают запись JSON через Core. Не представляйте их или протокольный smoke-тест как полный MVP E2E.
