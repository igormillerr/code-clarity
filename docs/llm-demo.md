# Демонстрация CodeClarity

## Подготовить смешанный пример

```powershell
python scripts/llm_demo.py --output .codeclarity/mixed-demo
```

Создаются два коммита нового Git-репозитория с Java и Python. Java-пример
усложняет чтение вложенными проверками; Python-пример сохраняет расчёт суммы,
но ухудшает имена. Они переиспользуются из Evals, без отдельной логики метрик.
`manifest.json` содержит точные SHA, repoRoot и отметку synthetic.

Настройте установленный плагин на этот repo по [инструкции](llm-setup.md), откройте
новый чат и запросите:

> Используй CodeClarity readability-review для Java/Python изменений main..HEAD.
> Сначала прочитай код и зафиксируй независимые Findings, затем запроси реальные
> метрики через MCP. Верни JSON/Markdown, доказательства, покрытие и пропуски.

Ожидаемый порядок: list changes → Git/AST → independent freeze → analyze →
correlation → основной отчёт → history. На существующем JAR честный итог —
INCOMPLETE: полезные численные результаты есть, но шесть обязательных метрик
не реализованы полностью. Не показывайте это как завершённый MVP.

Можно запустить тот же сценарий через реальный установленный Codex CLI:

```powershell
python scripts/llm_codex_probe.py --repo .codeclarity/mixed-demo/repo --output .codeclarity/mixed-live --mode review --temporary-repo-config
```

## Показать Rule Discovery

Тестовые истории: `evals/fixtures/history/sufficient.json` и `insufficient.json`.
Они содержат подготовленные **синтетические** находки/подтверждения; это не
исправления реальных пользователей. Для offline показа явно попросите
`rule-discovery` оценить supplied synthetic fixture без persistence. Выход:
`executionLevel: SYNTHETIC_SKILL_EVAL`, `synthetic: true`,
`decision: RULE_SUGGESTED` с PROPOSED-кандидатом или `decision: NO_SUGGESTION`
и пустой пользовательский текст. Это решение Skill, а не сохранение в Core.

Полное live-демо JSON History возможно только после передачи соответствующих
Tools участником 2: append → read-back → повтор того же reviewId без дубля →
подтверждённые тестовые события → propose → повтор без нового предложения.
В обычном сценарии без этих Tools статус UNAVAILABLE; файл истории вручную
не создаётся ради имитации интеграции.

## Резерв и репетиция

Презентация и PNG находятся в `docs/presentation/`. Реальные протокольные receipts
и результаты Evals сохраняются отдельно от скриншотов. Если live MCP недоступен,
покажите сохранённый проход с его точным уровнем проверки и ограничениями.
Протокольный тест нельзя выдавать за Codex E2E, а offline history — за persistence.

Перед совместным показом проверить: правильный repo-root, совпадение SHA,
четыре Skills/нужные Tools, freeze раньше метрик, отсутствие вымышленных чисел,
реальные source ranges, неполноту, идемпотентность истории после интеграции.
Совместная репетиция требует участия команды и пока не проведена.
