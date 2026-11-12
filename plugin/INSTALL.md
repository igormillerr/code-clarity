# Установка CodeClarity 0.4.0

В поставке находятся плагин **0.4.0**, MCP-сервер **0.1.7** и локальный
marketplace. Архив можно перенести на другой компьютер: сборка исходников там
не требуется. Если не оговорено иное, команды выполняются **из распакованной папки
`codeclarity-0.4.0`**, содержащей `plugin/` и `.agents/plugins/marketplace.json`.
При работе прямо из репозитория используйте его корневую папку.

Рядом с архивом передаётся `codeclarity-0.4.0.zip.sha256`. До распаковки,
из папки с ZIP, сравните его значение с результатом `Get-FileHash -Algorithm
SHA256 codeclarity-0.4.0.zip` в PowerShell, `sha256sum codeclarity-0.4.0.zip`
в Linux или `shasum -a 256 codeclarity-0.4.0.zip` в macOS. Внутренний
`SHA256SUMS` содержит контрольные суммы файлов поставки, `release.json` —
версии и состав пакета. Скрытая папка `.agents` также должна быть распакована.

## 1. Требования

| Компонент | Требование |
|---|---|
| Codex | Локальный Desktop или CLI с поддержкой плагинов; `codex plugin --help` должен работать |
| Java | **JDK 21+**, команды `java` и `javac` в `PATH` |
| Git | Команда `git` в `PATH`; проверяемый проект — существующий Git-репозиторий |
| Python | **3.10+** с модулем `venv` и `pip` |
| Python-зависимость | **`complexipy==8.3.0`**, устанавливается в выбранный интерпретатор |

JDK, Git, Python и complexipy не включены в архив. Maven и Node.js для установки
не нужны. Для `pip install` требуется доступ к источнику Python-пакетов.
Java- и Python-анализаторы входят в MCP JAR; complexipy устанавливается отдельно.

Это пакет с локальным stdio-процессом. Он предназначен для локальных клиентов
Codex, которые могут запускать Java и читать проверяемый репозиторий.
Для облачного Codex или браузерного клиента нужен отдельно организованный
доступ к серверу; этот архив его не создаёт.
Управляемая организацией установка также зависит от политики администратора.
Официальные требования к локальной поставке:
[Package your plugin](https://developers.openai.com/plugins/build/plugins),
[desktop-only plugins](https://developers.openai.com/plugins/deploy/desktop-only).

## 2. Настроить Python и выбрать репозиторий

Рекомендуется отдельное окружение: оно остаётся на этом компьютере и не попадает
в плагин. Скрипт `setup.py` проверяет зависимости, JDK и Git-проект, затем
записывает два абсолютных пути в `~/.codeclarity/python-path.txt` и
`~/.codeclarity/repo-root.txt`. Он не устанавливает Python-пакеты.

### Windows PowerShell 5.1 / 7

Распакуйте ZIP, перейдите в папку `codeclarity-0.4.0` и выполните:

```powershell
java -version
javac -version
git --version
codex plugin --help

$ccEnv = Join-Path ([Environment]::GetFolderPath('UserProfile')) '.codeclarity/venv'
py -3 -m venv $ccEnv
$ccPython = Join-Path $ccEnv 'Scripts/python.exe'
& $ccPython -m pip install -r plugin/requirements-python.txt
& $ccPython plugin/scripts/setup.py --python $ccPython --repo-root 'C:\work\my-project'
& $ccPython plugin/scripts/setup.py --check
```

Замените `C:\work\my-project` реальным путём к своему Git-репозиторию.
Если команды `py` нет, создайте окружение через установленный Python 3.10+:
`python -m venv $ccEnv`.

### Linux / macOS

```bash
java -version
javac -version
git --version
codex plugin --help

python3 -m venv "$HOME/.codeclarity/venv"
cc_python="$HOME/.codeclarity/venv/bin/python"
"$cc_python" -m pip install -r plugin/requirements-python.txt
"$cc_python" plugin/scripts/setup.py --python "$cc_python" --repo-root /path/to/my-project
"$cc_python" plugin/scripts/setup.py --check
```

Замените `/path/to/my-project` реальным Git-проектом. Если система сообщает
об отсутствии `venv` или `pip`, установите соответствующий пакет своего Python
и повторите создание окружения. На macOS команда `java -version` должна находить
именно установленный JDK, а не только системный launcher без Java runtime.

Можно использовать уже существующий Python с complexipy 8.3.0:
передайте его абсолютный путь через `--python`. Не копируйте готовое виртуальное
окружение между компьютерами. Для диагностического JSON добавьте `--json`.
`--check` только читает настройки и проверяет окружение; файлы не изменяет.

## 3. Установить плагин

Из корневой распакованной папки выполните:

```text
codex plugin marketplace add .
codex plugin add codeclarity@codeclarity-local
codex plugin list --marketplace codeclarity-local --json
```

Первая команда регистрирует marketplace, вторая устанавливает плагин.
В списке проверьте имя `codeclarity`, версию **0.4.0** и включённое состояние.
Не удаляйте и не перемещайте папку marketplace: она нужна для последующего
обновления. Путь может содержать пробелы; при передаче полного пути заключайте
его в кавычки.

В Desktop также можно открыть каталог плагинов, выбрать источник
**CodeClarity Local** и установить CodeClarity. Если локальный источник ещё
не появился, полностью перезапустите приложение. Интерфейс зависит от версии
Codex; CLI-команды выше проверяются через `codex plugin ... --help`.

После установки **перезапустите Codex и создайте новый сеанс**. Ранее открытый
сеанс может сохранять старые Skills и уже запущенный MCP-сервер.
Вызовы MCP появятся после загрузки плагина и успешного запуска Java.

## 4. Проверить работу

Откройте в Codex тот же репозиторий, который передали `setup.py`. Дайте запрос:

> Используй CodeClarity / readability-review для ревью Java- и Python-изменений
> между main и HEAD. Сначала прочитай исходники и зафиксируй независимое ревью,
> затем получи метрики и объясни их связь с замечаниями. Сохрани JSON и Markdown
> в .codeclarity/reviews. Явно укажи пропуски и ограничения.

Замените `main` нужной базовой веткой. Если изменений нет, нормальный результат —
`NO_CHANGES`. Для проверки анализа выберите диапазон с зафиксированными
изменениями функций или методов Java/Python.

Ожидается:

- Плагин предоставляет четыре Skills и **15 MCP-инструментов**: восемь основных
  и семь совместимых; список клиента может показывать их с префиксом плагина.
- Сервер разрешает Git-диапазон, читает зафиксированные снимки и получает
  **шесть метрик**: Cyclomatic Complexity, Cognitive Complexity, SLOC,
  глубину вложенности, число параметров и число возвратов.
- Независимый этап сохраняется до первого запроса метрик. Затем появляются
  JSON/Markdown с замечаниями, значениями обеих версий и доступностью данных.
- Полное ревью без замечаний получает `PASS`, с замечаниями — `WARN`.
  Неполные измерения или покрытие отражаются как `INCOMPLETE`.

Изменения полей, импортов, неподдерживаемых конструкций или неоднозначно
сопоставленных сущностей могут ограничить полноту отчёта. Значение метрики
само по себе не доказывает проблему читаемости.

История хранится в `.codeclarity/review-history.json` **проверяемого проекта**.
Если клиент запрашивает разрешение на `update_review_history`, разрешите запись
только для нужного ревью. Отказ не должен уничтожать основной отчёт.
При политике запрета записи история останется недоступна; не отключайте
подтверждения глобально ради установки. `FIXED`/`REJECTED` записывает оператор
отдельным CLI-действием, а предложения правил автоматически не активируются.

## 5. Обновить существующую установку 0.3.2

Распакуйте новый архив в постоянную папку и настройте зависимости по разделу 2.
Проверьте текущий источник:

```text
codex plugin marketplace list
```

Если `codeclarity-local` уже существует, но указывает на старую папку, сначала
перерегистрируйте именно этот источник. Из корня новой поставки:

```text
codex plugin remove codeclarity@codeclarity-local
codex plugin marketplace remove codeclarity-local
codex plugin marketplace add .
codex plugin add codeclarity@codeclarity-local
codex plugin list --marketplace codeclarity-local --json
```

Если источник уже указывает на обновлённую папку, достаточно удалить и повторно
установить `codeclarity@codeclarity-local` командами `plugin remove` и `plugin add`.
Затем перезапустите Codex. Не заменяйте файлы в `~/.codex/plugins/cache` вручную.
История проверяемого проекта находится вне кэша плагинов; сохраните её при
переносе самого проекта.

## 6. Переключить проект и устранить проблемы

- **Нужен другой репозиторий.** Повторите `setup.py --python <абсолютный путь>
  --repo-root <путь к новому Git-проекту>`, затем перезапустите MCP/Codex.
  Один сервер обслуживает выбранный репозиторий; название папки текущего чата
  само по себе не меняет этот выбор.
- **Нет `codex plugin` или локального marketplace.** Обновите локальный клиент
  Codex до версии с поддержкой плагинов и повторите `codex plugin --help`.
- **Не найден Java/Javac.** Установите JDK 21+, добавьте его `bin` в `PATH`
  и заново запустите Codex, чтобы приложение получило новое окружение.
- **Python Cognitive Complexity возвращает `ERROR`.** Запустите выбранный
  интерпретатор с `-m pip show complexipy`, проверьте версию 8.3.0 и повторите
  `setup.py --check`. Установка в другой Python не исправит выбранный worker.
- **Анализируется другой проект.** Проверьте `~/.codeclarity/repo-root.txt`
  и перезапустите сервер. Явно переданные `--repo-root` аргументы запуска
  имеют приоритет над файлом выбора проекта.
- **После изменения интерпретатора осталась старая ошибка.** Уберите устаревшее
  значение `CODECLARITY_PYTHON`, если оно задано: launcher предпочитает явную
  переменную файлу `python-path.txt`. Перезапустите сервер.
- **MCP не запускается из sandbox.** Предоставьте клиенту доступ к установленным
  JDK/Python и нужному репозиторию согласно его настройкам. Проверьте логи MCP;
  установка плагина не отменяет ограничения среды.
- **Не работают definition/references.** Это необязательная JDT LS-навигация.
  Для неё отдельно нужны подходящая распакованная Eclipse JDT LS и её Java
  runtime, заданные `~/.codeclarity/jdtls-home.txt` и `jdtls-java.txt`
  либо `CODECLARITY_JDTLS_HOME` / `CODECLARITY_JDTLS_JAVA`.
  Метрики и AST-контекст работают без JDT LS. Навигация относится к рабочему
  дереву, а основной анализ — к Git-снимкам.

`setup.py` допускает отдельную папку диагностики через `--config-dir`, но
штатный launcher читает `~/.codeclarity`. Для обычной установки оставьте
папку по умолчанию.

## Удаление

```text
codex plugin remove codeclarity@codeclarity-local
codex plugin marketplace remove codeclarity-local
```

Затем перезапустите Codex. Удаление из клиента не удаляет Python-окружение,
файлы выбора в `~/.codeclarity` или историю в проверяемом проекте.
