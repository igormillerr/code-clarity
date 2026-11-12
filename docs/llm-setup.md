# CodeClarity: локальная установка и запуск LLM-части

В `codex/llm-workflow` объединены Python `dc9d957` и Java Core с исправлениями
`afe8b08`. Версия пакета плагина — `0.4.0`, сервера — `0.1.7`.
Сервер предоставляет шесть метрик каждого языка, универсальные MCP Tools,
JSON-историю и предложения правил. Проверяйте фактическую доступность измерений.
Требуются JDK 21+ (с компилятором для Java source-file launcher), Git, Python с зависимостями и локальный Codex с поддержкой
плагинов. Использовавшаяся версия CLI — `0.167.0-alpha.3.2`;
фактические результаты текущей интеграции — в [статусе](llm-status.md).

## Python-окружение

Для всех шести Python-метрик требуется **complexipy 8.3.0** из
`requirements-python.txt`. Установите её в отдельное окружение. PowerShell,
из корня проекта:

```powershell
python -m venv .venv
& '.venv/Scripts/python.exe' -m pip install -r requirements-python.txt
$codeclarityPython = (Resolve-Path '.venv/Scripts/python.exe').Path
$env:CODECLARITY_PYTHON = $codeclarityPython
```

Для проверки Skills и полной JSON Schema дополнительно доступны закреплённые
инструменты из `requirements-llm-dev.txt`:

```powershell
& $codeclarityPython -m pip install -r requirements-llm-dev.txt
```

Переменная содержит путь к одному исполняемому файлу, без аргументов.
Worker запускается с `-I`: установка зависимости через `pip --user` не заменяет
установку в выбранный интерпретатор. При отсутствии или другой версии complexipy
CogC получает `ERROR`, остальные пять метрик и AST продолжают работать;
отчёт будет частичным.

## Выбор Python для установленного плагина

Плагин запускает Java 21 source-file launcher
`plugin/scripts/LaunchMcp.java`, который передаёт STDIO поставленному Core JAR.
Он выбирает интерпретатор в таком порядке:

1. Непустая переменная `CODECLARITY_PYTHON`, если хост передал её launcher.
2. UTF-8 файл `~/.codeclarity/python-path.txt` с одним абсолютным путём к Python.
3. Стандартный выбор Core — `python` из PATH, если selector не задан.

Проверяемый плагинный loader не принимает `env_vars`, а пользовательское
окружение может фильтроваться хостом. Поэтому для desktop настройте файл:

```powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\.codeclarity" | Out-Null
Set-Content -LiteralPath "$env:USERPROFILE\.codeclarity\python-path.txt" -Value $codeclarityPython -Encoding utf8NoBOM
```

Файл содержит путь к исполняемому файлу без аргументов. Launcher явно передаёт
выбранный путь дочернему Core-процессу. Изменения ограничены упаковкой плагина:
анализаторы, алгоритмы и поставленный JAR этим launcher не меняются.

На Linux/macOS используйте `.venv/bin/python`:

```bash
export CODECLARITY_PYTHON="$(pwd)/.venv/bin/python"
mkdir -p ~/.codeclarity
printf '%s\n' "$CODECLARITY_PYTHON" > ~/.codeclarity/python-path.txt
```

Для CLI можно использовать переменную в текущей оболочке. На Windows её также
можно сохранить для пользователя:

```powershell
[Environment]::SetEnvironmentVariable('CODECLARITY_PYTHON', $codeclarityPython, 'User')
```

Существующее приложение получит изменённую пользовательскую переменную после
перезапуска; переданная переменная имеет приоритет над файлом. Файл selector
читается при старте launcher, поэтому после его изменения перезапустите
MCP-сервер/сеанс плагина. Для чтения файла полный перезапуск приложения не нужен.
В `mcp.json` остаются только `type`, `command`, `args` и `cwd`.

## Необязательная Java LSP-навигация

Для definition/references нужен отдельно распакованный JDT LS. Его отсутствие
не мешает основному AST/metric review. Launcher выбирает непустые переменные
CODECLARITY_JDTLS_HOME/CODECLARITY_JDTLS_JAVA, а при фильтрации окружения хостом —
UTF-8 файлы `~/.codeclarity/jdtls-home.txt` и `~/.codeclarity/jdtls-java.txt`.
Каждый файл содержит один абсолютный путь: каталог JDT LS и исполняемый Java
подходящей для этого дистрибутива версии. Python selector настраивается отдельно.

```powershell
Set-Content -LiteralPath "$env:USERPROFILE\.codeclarity\jdtls-home.txt" -Value 'C:\tools\jdtls' -Encoding utf8NoBOM
Set-Content -LiteralPath "$env:USERPROFILE\.codeclarity\jdtls-java.txt" -Value 'C:\tools\jdk\bin\java.exe' -Encoding utf8NoBOM
```

После смены настроек нужен новый MCP-процесс. LSP возвращает WORKTREE-контекст;
для ревью другого Git SHA сначала проверьте соответствие рабочего файла снимку.

## Установка плагина

```powershell
codex plugin marketplace add .
codex plugin add codeclarity@codeclarity-local
codex plugin list --marketplace codeclarity-local --json
```

JAR выбирает один репозиторий из UTF-8 файла `~/.codeclarity/repo-root.txt`.
Укажите абсолютный путь к анализируемому проекту:

```powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\.codeclarity" | Out-Null
Set-Content -LiteralPath "$env:USERPROFILE\.codeclarity\repo-root.txt" -Value 'C:\work\my-project' -Encoding utf8NoBOM
```

Это смена анализируемого репозитория: сохраните прежний путь, если он ещё нужен.
Домашние `repo-root.txt` и `python-path.txt` выбирают соответственно репозиторий
и интерпретатор. Проектной `.codeclarity/review-history.json` управляет Core.

Java должна быть в PATH. Плагин подключает один MCP-сервер через STDIO;
регистрировать каждый Tool или второй сервер через `codex mcp add` не требуется.
Если ранее была ручная регистрация, проверьте `codex mcp list` и выберите один
способ подключения, чтобы избежать дублирования.

После установки или обновления откройте новый локальный чат. Доступны:

- `codeclarity:readability-review` — полный процесс;
- `codeclarity:independent-review` — качественный поиск до текущих измерений;
- `codeclarity:metrics-correlation` — сопоставление Findings с измерениями;
- `codeclarity:rule-discovery` — предложения по подтверждённой истории при доступных Core Tools.

Пример запроса:

> Используй CodeClarity readability-review для Python-изменений между main и HEAD.
> Сначала прочитай код и зафиксируй независимые Findings, затем вызови анализ
> метрик через MCP. Верни JSON/Markdown, покрытие, пропуски и вердикт. Исходники не меняй.

Сравниваются зафиксированные коммиты: база — общий предок `main` и `HEAD`.
Запрос на worktree/staged нельзя незаметно заменять этим режимом.

## Полнота и matching

Java/Python и смешанное ревью могут завершиться `PASS` или `WARN`, если обработаны
исходники, обязательные этапы и все шесть метрик. Недоступные метрики,
неподтверждённое сопоставление и непокрытые изменённые строки отражаются явно.
`ok` от сервера само по себе не доказывает полноту.

Core возвращает `files[].matches`: логические группы со статусом, ключом,
сигнатурами и диапазонами обеих сторон. Изменение параметров Python-функции
может сохранять `MATCHED` и измеренную delta. Skills сохраняют эти данные в
`entityMatches`, не воспроизводят matching средствами LLM.
Независимый этап считает исходные сущности снимков (`SNAPSHOT_ENTITY`),
а итоговое покрытие — группы Core (`MATCH_GROUP`); эти количества могут различаться.
Недоступность необязательного LSP или истории сама по себе не отменяет полный
основной отчёт.

## Диагностика

| Симптом | Проверка |
|---|---|
| Плагина нет | Marketplace root, `plugin/plugin.json`, `codex plugin list --available --json` |
| Skills есть, MCP нет | PATH Java, JAR, абсолютный repo-root.txt, stderr MCP |
| Tools дублируются | Plugin connection и ручная регистрация `codex mcp list` |
| Python CogC ERROR | Приоритетная `CODECLARITY_PYTHON`, затем `python-path.txt`; установка complexipy **8.3.0** в выбранный Python; новый запуск launcher после смены selector |
| Python partial | Причины в warnings и отдельных метриках; сохранить доступные пять значений и Java-результат |
| История UNAVAILABLE | Проверить get_review_history/update_review_history/propose_rule_candidate и права выбранного Git-репозитория; прямой записью JSON ошибку не компенсировать |
| Сервер ok, ревью INCOMPLETE | Проверить шесть метрик, source coverage, статусы matches и обязательные этапы |

Запущенный без протокольного клиента JAR может просто ожидать stdin.
Отсутствие вывода не подтверждает работоспособность интеграции.

## Проверки

Запускайте тесты выбранным интерпретатором:

```powershell
& $codeclarityPython plugin/skills/readability-review/scripts/review_ids.py --self-test
& $codeclarityPython scripts/llm_evals.py self-test
& $codeclarityPython scripts/llm_artifact_test.py
& $codeclarityPython scripts/llm_evals.py protocol --jar plugin/server/codeclarity-mcp.jar --output .codeclarity/protocol-new
```

Каждый каталог fixture/output должен быть новым или пустым. Создавайте Git fixture
и запускайте MCP под одним пользователем ОС: Git отклоняет другой owner как
`dubious ownership`. В некоторых Windows sandbox Java также получает
`AccessDeniedException` при чтении Git root. Это ошибки окружения;
их нельзя считать успешным тестом или обходить глобальным `safe.directory` ради демо.

Реальный Python-only запуск установленного плагина:

```powershell
& $codeclarityPython scripts/llm_demo.py --source python-experiments --output .codeclarity/python-demo-new
& $codeclarityPython scripts/llm_codex_probe.py --repo .codeclarity/python-demo-new/repo --output .codeclarity/python-live-new --mode review --languages python --python $codeclarityPython --temporary-repo-config
& $codeclarityPython scripts/llm_codex_evidence.py --run .codeclarity/python-live-new --output evals/results/codex-python-new.json --languages python
```

Probe запускает Codex с `--no-daemon` и явно передаёт выбранный Python в окружение;
для хоста, фильтрующего его, используется настроенный `python-path.txt`.
`--temporary-repo-config`
временно задаёт домашний repo-root.txt и восстанавливает его после завершения.
Параллельно не запускайте сеансы с этим сервером; обнаруженное чужое изменение
конфигурации сохраняется. Без флага используется отдельный Java user.home через
JAVA_TOOL_OPTIONS, которую некоторые клиенты не передают MCP-процессу.

Проверка JSONL сверяет реальные Tools, freeze до **начала** analyze, неизменность
Findings, source ranges и измерения. Успешного exit code CLI недостаточно.
Фактический статус и ссылки на текущие результаты — в [llm-status.md](llm-status.md).
Старые `evals/results/*baseline*`, `agent-forward.json` и `codex-live.json` остаются
историческими снимками; новые результаты сохраняются в отдельных файлах.

Формат упаковки и запуск локального MCP описаны в официальных страницах
[Package your plugin](https://developers.openai.com/plugins/build/plugins) и
[MCP configuration](https://learn.chatgpt.com/docs/extend/mcp?surface=cli).
Публичная публикация плагина в эту работу не входит.
