# CodeClarity: локальная установка и запуск LLM-части

Пакет плагина — `0.2.0`, текущий сервер — `0.1.6`. Он включает единый MCP API,
шесть Java-метрик и JSON-память через get_review_history/update_review_history.
Для необязательных LSP definition/references настрой CODECLARITY_JDTLS_HOME и
при необходимости CODECLARITY_JDTLS_JAVA. Это WORKTREE-контекст; запуск JDT LS
не требуется для метрик или основного ревью. Подробности и ограничения — в README.
Основа исторической LLM-части — `feature/python ec6a3ed`. Требуются Java 21+, Git, Python 3.10+
и локальный Codex с поддержкой плагинов. Проверяемая здесь версия CLI:
`0.167.0-alpha.3.2`.

## Установка

Из корня репозитория, PowerShell:

```powershell
codex plugin marketplace add .
codex plugin add codeclarity@codeclarity-local
codex plugin list --marketplace codeclarity-local --json
```

Текущий JAR выбирает один репозиторий из UTF-8 файла
`~/.codeclarity/repo-root.txt`. Укажите абсолютный путь к анализируемому проекту:

```powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\.codeclarity" | Out-Null
Set-Content -LiteralPath "$env:USERPROFILE\.codeclarity\repo-root.txt" -Value 'C:\work\my-project' -Encoding utf8NoBOM
```

Это явная смена анализируемого репозитория: существующий путь следует сохранить,
если он ещё нужен. Не путать домашний файл выбора репозитория с проектной
`.codeclarity/review-history.json`, которой управляет Core.

Для Python при необходимости задайте `CODECLARITY_PYTHON` равной пути к одному
интерпретатору, без аргументов. Переменная должна быть доступна процессу Codex.
Java должна быть в PATH. Плагин сам подключает один MCP-сервер через STDIO;
добавлять каждый Tool или второй сервер через `codex mcp add` не требуется.
Если сервер ранее зарегистрирован вручную, проверьте `codex mcp list` и выберите
один способ подключения. Автоматически удалять чужие регистрации не нужно.

Откройте новый локальный чат после установки/обновления. Доступны:

- `codeclarity:readability-review` — полный процесс;
- `codeclarity:independent-review` — качественный поиск до численных результатов;
- `codeclarity:metrics-correlation` — интерпретация реальных измерений;
- `codeclarity:rule-discovery` — история и предложения при доступных Core Tools.

Пример запроса:

> Используй CodeClarity readability-review для Java/Python изменений между main и HEAD.
> Сохрани независимые замечания до получения метрик, затем верни JSON/Markdown,
> покрытие, пропуски и вердикт. Не меняй исходники.

Сейчас сравниваются только коммиты, причём база — общий предок `main` и `HEAD`.
Запрос на worktree/staged нельзя незаметно заменять этим режимом.

## Что проверять при ошибке

| Симптом | Проверка |
|---|---|
| Плагина нет в списке | Корень marketplace, `plugin/plugin.json`, вывод `codex plugin list --available --json` |
| Skills есть, MCP нет | PATH Java; наличие JAR; абсолютный repo-root.txt; запуск JAR вручную с `--repo-root`; stderr MCP |
| Инструменты отображаются дважды | Сравнить plugin connection и ручную регистрацию `codex mcp list` |
| Python partial | PATH/`CODECLARITY_PYTHON`, синтаксис и предупреждения; не терять Java-результат |
| История UNAVAILABLE | Проверить наличие get_review_history/update_review_history и версию подключённого JAR. Операция сохранения кандидатов правил пока отсутствует; JSON напрямую не подменять |
| Сервер ok, отчёт INCOMPLETE | В прототипе не хватает обязательных метрик; полнота MVP проверяется отдельно |

Успешный запуск JAR без протокольного клиента может просто ожидать stdin.
Для воспроизводимой проверки используйте команды ниже, а не отсутствие вывода.

## Проверки

```powershell
python plugin/skills/readability-review/scripts/review_ids.py --self-test
python scripts/llm_evals.py self-test
python scripts/llm_artifact_test.py
python scripts/llm_evals.py protocol --jar plugin/server/codeclarity-mcp.jar --output .codeclarity/protocol-run
```

Каждый `--output` с тестовым репозиторием должен указывать новый/пустой каталог.
В ограниченном Windows sandbox Java может получить `AccessDeniedException` при
чтении корня Git; такой запуск — ошибка окружения, а не успешный протокольный тест.
Создавайте тестовый репозиторий и запускайте MCP под одним пользователем ОС:
Git также отклоняет fixture другого владельца как `dubious ownership`. Для
этого теста достаточно нового fixture под нужным пользователем; изменять
глобальный список `safe.directory` не требуется.

Проверка установленного плагина реальным Codex CLI:

```powershell
python scripts/llm_evals.py prepare --scenario python-naming --output .codeclarity/naming-fixture
python scripts/llm_codex_probe.py --repo .codeclarity/naming-fixture/repo --output .codeclarity/codex-probe --mode discovery --temporary-repo-config
```

`--temporary-repo-config` временно задаёт домашний repo-root.txt и восстанавливает
его после запуска. При обнаружении параллельного изменения конфигурации скрипт
сохраняет чужое изменение и пишет предупреждение. Запускайте probe без параллельных
сеансов, использующих этот сервер. Без флага используется изолированный Java
user.home через JAVA_TOOL_OPTIONS; некоторые клиенты не передают эту переменную
MCP-процессу. Успех CLI сам по себе не доказывает вызов Tool: проверяйте events.jsonl
и stderr. Режим `--mode review` запускает полный Skill на той же конфигурации.

Завершённый полный прогон можно проверить по исходным JSONL-событиям:

```powershell
python scripts/llm_codex_evidence.py --run .codeclarity/live-run --output evals/results/codex-live-new.json
```

Проверка сверяет реальные MCP-ответы, порядок freeze до НАЧАЛА analyze,
неизменность Findings, source ranges и все численные объекты. Она не считает
успешный exit code достаточным доказательством. Фактический статус этой поставки:
[llm-status.md](llm-status.md).

Формат упаковки и `${PLUGIN_ROOT}` сверены с официальными страницами:
[Package your plugin](https://developers.openai.com/plugins/build/plugins),
[Local MCP servers](https://developers.openai.com/plugins/deploy/desktop-only).
Публичная публикация плагина не входит в эту работу.
