# Dev Spec: MCP Project Updater

## 1. Назначение

Разработать набор утилит для автоматического обновления MCP-индекса проекта 1С из Git.

Основной компонент:

```text
update_mcp_project.py
```

Это кроссплатформенное Python-ядро, которое выполняет:

```text
Git update / HEAD detection
  ↓
staging/build
  ↓
generate-config-report
  ↓
metadata/Report.txt + code/
  ↓
MCP build container
  ↓
smoke-test
  ↓
switch build → current
  ↓
production MCP restart
  ↓
state update
```

Вспомогательные компоненты:

```text
update-mcp-project.ps1  — тонкая Windows-обертка для Task Scheduler
mcp_smoke_test.py       — MCP tool smoke-test
```

`generate-config-report` считается готовым внешним компонентом. Он вызывается updater-ом как CLI и формирует `Report.txt`, diagnostics и logs. Парсер поддерживает config JSON, `mainConfigPath`, `extensionPath`, `mainConfigRequired`, `extensionRequired`, `buildXmlOverrides`, `generatorSettingsPath`, diagnostics и logs.

---

## 2. Ключевые проектные решения

### 2.1. Python — ядро, PowerShell — только wrapper

Запрещено реализовывать бизнес-логику updater-а в PowerShell.

Правильно:

```text
update_mcp_project.py
  вся логика обновления, staging, Docker, smoke-test, switch, rollback

update-mcp-project.ps1
  только принимает параметры, вызывает Python, возвращает exit code
```

### 2.2. Jenkins/GitLab CI Runner не используются в MVP

MVP запускается через Windows Task Scheduler.

При этом код должен быть готов к будущему запуску на Linux:

```bash
python3 update_mcp_project.py --config /opt/mcp-1c/projects/orders.json
```

### 2.3. Один проект = один MCP production endpoint

Для каждой конфигурации/проекта свой MCP:

```text
orders production → http://localhost:8100/mcp
orders build      → http://localhost:18100/mcp

zup production    → http://localhost:8200/mcp
zup build         → http://localhost:18200/mcp
```

Внутри контейнера MCP слушает порт `8000`, а снаружи используется свой `hostPort` через Docker mapping `-p <hostPort>:8000`.

### 2.4. Ready по логам не является гарантией готовности индекса

Логи используются только как диагностика.

Готовность build-индекса для switch должна подтверждаться:

```text
1. infrastructure smoke-test;
2. MCP tool smoke-test, если включен.
```

`mcp_smoke_test.py` должен быть полноценным MCP-клиентом, а не простым `curl`.

---

## 3. Целевая структура проекта updater-а

```text
mcp_project_updater/
  __init__.py
  cli.py
  config.py
  constants.py
  errors.py
  logging_setup.py

  git_ops.py
  source_detector.py
  staging.py
  parser_runner.py
  report_validator.py

  docker_ops.py
  mcp_container.py
  smoke_infrastructure.py
  smoke_tool.py

  state.py
  lock.py
  switcher.py
  rollback.py
  notifications.py

  utils.py

update_mcp_project.py
update-mcp-project.ps1

mcp_smoke_test/
  __init__.py
  cli.py
  client.py
  result.py

mcp_smoke_test.py

tests/
  test_config.py
  test_source_detector.py
  test_report_validator.py
  test_state.py
  test_lock.py
  test_switcher.py
  test_notifications.py
```

Для MVP допустимо держать модули в одной папке без установки пакета, но структура должна позволять позже сделать installable CLI.

---

## 4. CLI

### 4.1. Основной Python CLI

```powershell
python E:\mcp-1c\tools\mcp-project-updater\update_mcp_project.py `
  --config E:\mcp-1c\projects\orders.json
```

### 4.2. CLI параметры

```text
--config <path>       обязательный путь к project.json
--force               переиндексировать текущий commit даже без изменений
--no-git-pull         не делать git fetch/pull, использовать текущий HEAD
--rollback            выполнить ручной rollback current ↔ previous
--verbose             подробный лог
--dry-run             проверить config/source/state без parser/Docker/switch
```

### 4.3. PowerShell wrapper

Файл:

```text
update-mcp-project.ps1
```

Поведение:

```text
1. принимает -Config, -Force, -NoGitPull, -Rollback, -Verbose, -DryRun;
2. собирает аргументы для update_mcp_project.py;
3. вызывает python;
4. возвращает $LASTEXITCODE.
```

Логика Git, Docker, state, switch, rollback в `.ps1` запрещена.

---

## 5. Config schema

### 5.1. Полный пример

```json
{
  "project": "orders",

  "repo": {
    "path": "E:/mcp-1c/repos/orders",
    "branch": "master",
    "remote": "origin",
    "pullMode": "ff-only"
  },

  "sources": {
    "mainConfigPath": "src/cf",
    "mainConfigRequired": false,
    "extensionPath": "src/cfe",
    "extensionRequired": false
  },

  "parser": {
    "toolPath": "E:/mcp-1c/tools/generate-config-report/generate_config_report.py",
    "encoding": "utf-8",
    "warningsAsErrors": false,
    "buildXmlOverrides": true,
    "allowedExitCodes": [0, 1]
  },

  "mcp": {
    "image": "comol/1c_code_metadata_mcp:latest",
    "containerPort": 8000,

    "production": {
      "containerName": "mcp-orders",
      "hostPort": 8100,
      "url": "http://localhost:8100/mcp"
    },

    "build": {
      "containerName": "mcp-orders-build",
      "hostPort": 18100,
      "url": "http://localhost:18100/mcp"
    },

    "indexCode": true,
    "indexMetadata": true,
    "indexHelp": false,

    "resetDatabaseOnBuild": true,
    "resetCache": false,
    "useSse": false,
    "useGpu": false,

    "env": {
      "METADATA_PATH": "/app/metadata",
      "CODE_PATH": "/app/code",
      "OPENAI_API_BASE": "http://host.docker.internal:1234/v1",
      "OPENAI_API_KEY": "lm-studio",
      "OPENAI_MODEL": "Qwen3-Embedding-4B"
    },

    "secretEnv": {
      "LICENSE_KEY": "ONERPA_LICENSE_KEY"
    }
  },

  "paths": {
    "stagingRoot": "E:/mcp-1c/staging/orders",
    "chromaRoot": "E:/mcp-1c/chroma/orders",
    "stateRoot": "E:/mcp-1c/state/orders",
    "logsRoot": "E:/mcp-1c/logs/orders"
  },

  "smokeTest": {
    "enabled": true,
    "profile": "production",

    "reportValidation": {
      "enabled": true,
      "requiredReportPatterns": [
        "^\\s*-\\s*Конфигурации\\.",
        "Имя: \"",
        "Синоним: \"",
        "Комментарий: \""
      ],
      "forbiddenReportPatterns": [
        "Модуль менеджера",
        "Модуль объекта",
        "Модуль формы",
        "ПутьКФайлу",
        "ФайлBSL",
        "code/main",
        "code/extensions",
        "src/cf",
        "src/cfe",
        "ПоисковыеТеги",
        "Источник: Основная конфигурация",
        "Источник: Расширение"
      ]
    },

    "infrastructure": {
      "enabled": true,
      "timeoutSeconds": 7200,
      "checkIntervalSeconds": 15,
      "httpReadyUrl": "http://localhost:18100/mcp",
      "acceptableHttpStatusCodes": [200, 400, 404, 405],
      "requireChromaNotEmpty": true,
      "logTailLines": 300,
      "logErrorPatterns": [
        "Traceback",
        "Exception",
        "CRITICAL",
        "failed",
        "FAILED",
        "Ошибка",
        "ошибка"
      ]
    },

    "toolSmokeTest": {
      "enabled": true,
      "toolPath": "E:/mcp-1c/tools/mcp-smoke-test/mcp_smoke_test.py",
      "url": "http://localhost:18100/mcp",
      "timeoutSeconds": 7200,

      "metadataToolName": "metadatasearch",
      "metadataQueryArgument": "query",
      "metadataQueries": [
        "Конфигурации",
        "Документы",
        "Справочники"
      ],

      "codeToolName": "codesearch",
      "codeQueryArgument": "query",
      "codeQueries": [
        "Процедура",
        "Функция"
      ]
    }
  },

  "notifications": {
    "enabled": true,
    "onSuccess": false,
    "onFailure": true,
    "onRollback": true,
    "webhookUrlEnv": "MCP_UPDATE_WEBHOOK_URL"
  },

  "rollback": {
    "preserveFailedIndex": true
  },

  "retention": {
    "keepPreviousIndexes": 1,
    "keepLogsDays": 30,
    "keepStagingBuilds": 2
  }
}
```

### 5.2. Config validation

`config.py` должен проверять:

```text
project не пустой
repo.path существует или ошибка
paths.* заданы
mcp.containerPort > 0
mcp.production.hostPort > 0
mcp.build.hostPort > 0
mcp.production.hostPort != mcp.build.hostPort
mcp.production.containerName != mcp.build.containerName
parser.toolPath существует
если notifications.enabled=true и onFailure/onRollback=true:
  webhookUrlEnv задан
если smokeTest.profile не указан:
  использовать default "dev"
если smokeTest.profile not in ["dev", "production"]:
  config validation error
если smokeTest.profile="production" и toolSmokeTest.enabled=false:
  config validation error
если rollback.preserveFailedIndex не указан:
  использовать default true
```

Secret env проверяются отдельно перед Docker/notifications.

---

## 6. State model

Каталог:

```text
stateRoot/
  last_indexed_commit
  current_commit
  previous_commit
  lock
```

### 6.1. `last_indexed_commit`

Содержит SHA commit, который успешно прошел:

```text
parser
Report validation
MCP build
smoke-test
switch
production smoke-test
```

Файл обновляется только в конце successful switch.

### 6.2. `current_commit`

Commit текущего production-индекса.

### 6.3. `previous_commit`

Commit предыдущего индекса, доступного для rollback.

### 6.4. `lock`

JSON:

```json
{
  "pid": 1234,
  "startedAt": "2026-05-12T10:30:00",
  "project": "orders",
  "mode": "update"
}
```

Lock снимается в `finally`.

---

## 7. Exit codes

```text
0  — обновление успешно выполнено или изменений нет
1  — обновление выполнено, есть некритичные warnings
2  — ошибка config-файла updater-а
3  — не найден Git-репозиторий
4  — рабочее дерево Git содержит tracked changes
5  — git fetch/pull failed
6  — отсутствуют оба источника: src/cf и src/cfe
7  — mainConfigRequired=true, но src/cf отсутствует
8  — extensionRequired=true, но src/cfe отсутствует
9  — parser failed
10 — Report.txt failed validation
11 — Docker unavailable
12 — MCP build container failed
13 — MCP build smoke-test failed
14 — production switch failed
15 — production smoke-test failed
16 — rollback failed
17 — lock already exists / update already running
18 — missing required secret env
19 — invalid state / cannot determine current index
```

Notification failure policy:

```text
notification failed после успешного update:
  exit code 1
  статус: success with warning
  production MCP остается успешным
  last_indexed_commit уже обновлен

notification failed после failed update:
  сохранить исходный exit code ошибки update
  notification failure записать warning

notification failed после rollback:
  сохранить rollback/failure exit code
  notification failure записать warning
```

Ошибка уведомления не должна маскировать первопричину ошибки и не должна превращать успешный production update в hard fail.

Exit code `20` не используется в основном workflow. Notification failure после успешного update возвращает exit code `1`, а после failed update/rollback сохраняет исходный код ошибки.

---

## 8. Main workflow

### 8.1. `run_update(config, options)`

Алгоритм:

```text
1. load config
2. setup logging
3. acquire lock
4. validate secrets
5. validate Git repository
6. determine target commit
7. compare with last_indexed_commit
8. if no changes and not force:
     log no changes
     exit 0
9. detect sources
10. prepare build staging
11. generate parser config
12. run parser
13. validate Report.txt
14. prepare build code directory
15. prepare chroma/build
16. start build MCP container
17. run infrastructure smoke-test
18. run tool smoke-test if enabled
19. switch build → current
20. start production MCP
21. run production smoke-test: production infrastructure smoke-test + MCP tool smoke-test if `toolSmokeTest.enabled=true`
22. update state files
23. send success notification if enabled
24. cleanup/retention
25. release lock
```

### 8.2. Failure behavior

Если ошибка до switch:

```text
production MCP не трогать
last_indexed_commit не обновлять
build container остановить
build artifacts сохранить
failure notification отправить
exit code по ошибке
```

Если ошибка после switch:

```text
попытаться rollback
last_indexed_commit не обновлять
rollback notification отправить
exit code 15 или 16
```

---

## 9. Git operations

Модуль:

```text
git_ops.py
```

### 9.1. Проверка repo

Команды:

```bash
git rev-parse --is-inside-work-tree
git status --porcelain
```

Tracked changes считаются ошибкой.

Для MVP untracked files можно игнорировать, но желательно логировать warning.

### 9.2. Обычный режим

```bash
git fetch <remote> <branch>
git checkout <branch>
git pull --ff-only <remote> <branch>
git rev-parse <remote>/<branch>
```

`target_commit = origin/master` или другой configured remote/branch.

### 9.3. `--no-git-pull`

```bash
git rev-parse HEAD
```

`fetch/pull` не выполняются.

### 9.4. `--force`

Если `--force` включен, updater не выходит при совпадении:

```text
target_commit == last_indexed_commit
```

а выполняет полную переиндексацию.

---

## 10. Source detection

Модуль:

```text
source_detector.py
```

Вход:

```text
repo.path
sources.mainConfigPath
sources.mainConfigRequired
sources.extensionPath
sources.extensionRequired
```

Выход:

```json
{
  "mainExists": true,
  "extensionExists": false,
  "mainPath": "E:/mcp-1c/repos/orders/src/cf",
  "extensionPath": null
}
```

Правила exit codes:

```text
mainConfigRequired=true, src/cf missing       → exit 7
extensionRequired=true, src/cfe missing       → exit 8
both sources missing                          → exit 6
```

---

## 11. Staging

Модуль:

```text
staging.py
```

### 11.1. Каталоги build

Перед каждым build удалять и создавать:

```text
staging/build/metadata
staging/build/code
staging/build/diagnostics
staging/build/logs
staging/build/settings
```

### 11.2. Parser config

Файл:

```text
staging/build/parser-config.json
```

Генерируется updater-ом.

Обязательно задавать:

```json
"generatorSettingsPath": "<stagingRoot>/build/settings/<project>.xml-overrides.json"
```

Причина: если не указать `generatorSettingsPath`, parser создаст generated overrides в своей папке `generate_config_report/settings/generated/<project>.xml-overrides.json`; для updater-а это нежелательно, потому что build должен быть самодостаточным и не должен модифицировать tool directory.

---

## 12. Parser runner

Модуль:

```text
parser_runner.py
```

Команда:

```bash
python <parser.toolPath> --config <staging/build/parser-config.json>
```

Если updater запущен с `--verbose`, добавить:

```text
--verbose
```

Если требуется строгий режим:

```text
--strict
```

Но основное управление strict должно идти через parser config:

```json
"warningsAsErrors": false
```

Допустимые коды:

```json
allowedExitCodes: [0, 1]
```

Если parser вернул другой код:

```text
exit 9
не запускать Docker
```

---

## 13. Report validation

Модуль:

```text
report_validator.py
```

Проверки:

```text
Report.txt существует
размер > 0
есть хотя бы одна корневая секция
есть required patterns
нет forbidden patterns
diagnostics/errors = 0
```

Корневой regex:

```regex
^\s*-\s*Конфигурации\.
```

Причина: parser README фиксирует, что корневая секция начинается с табуляции перед `-`.

Forbidden patterns брать из config.

---

## 14. CODE_PATH preparation

Модуль:

```text
staging.py
```

Копирование:

```text
repo/src/cf  → staging/build/code/cf
repo/src/cfe → staging/build/code/cfe
```

Копировать только существующие источники.

Запрещено:

```text
смешивать cf и cfe
переименовывать объекты
модифицировать XML/BSL
```

Рекомендуемая реализация:

```text
shutil.copytree(..., dirs_exist_ok=False)
```

Перед копированием `build/code` должен быть пустым.

---

## 15. Docker operations

Модули:

```text
docker_ops.py
mcp_container.py
```

### 15.1. Проверка Docker

Команда:

```bash
docker version
```

Если Docker недоступен:

```text
exit 11
```

### 15.2. Удаление старого build container

Перед запуском build:

```bash
docker rm -f <buildContainerName>
```

Ошибку “container not found” игнорировать.

### 15.3. Build container run

Команда должна собираться из config.

Пример:

```powershell
docker run -d --name mcp-orders-build `
  -e LICENSE_KEY="<from env>" `
  -e METADATA_PATH="/app/metadata" `
  -e CODE_PATH="/app/code" `
  -e RESET_CACHE=false `
  -e RESET_DATABASE=true `
  -e USESSE=false `
  -e OPENAI_API_BASE="http://host.docker.internal:1234/v1" `
  -e OPENAI_API_KEY="lm-studio" `
  -e OPENAI_MODEL="Qwen3-Embedding-4B" `
  -p 18100:8000 `
  -v "E:/mcp-1c/staging/orders/build/metadata:/app/metadata" `
  -v "E:/mcp-1c/staging/orders/build/code:/app/code" `
  -v "E:/mcp-1c/chroma/orders/build:/app/chroma_db" `
  comol/1c_code_metadata_mcp:latest
```

Если `useGpu=true`, добавить:

```text
--gpus all
```

### 15.4. Production container run

После switch:

```powershell
docker run -d --name mcp-orders `
  ... `
  -e RESET_DATABASE=false `
  -p 8100:8000 `
  -v "E:/mcp-1c/staging/orders/current/metadata:/app/metadata" `
  -v "E:/mcp-1c/staging/orders/current/code:/app/code" `
  -v "E:/mcp-1c/chroma/orders/current:/app/chroma_db" `
  comol/1c_code_metadata_mcp:latest
```

Production не должен запускаться с `RESET_DATABASE=true`.

---

## 16. Infrastructure smoke-test

Модуль:

```text
smoke_infrastructure.py
```

Проверки в цикле до timeout:

```text
docker inspect container exists
State.Status == running
State.Restarting == false
build hostPort доступен
HTTP endpoint отвечает допустимым status code
chroma/build существует
chroma/build не пустой, если requireChromaNotEmpty=true
docker logs не содержит error patterns
```

### 16.1. HTTP check

URL:

```text
smokeTest.infrastructure.httpReadyUrl
```

Обычно:

```text
http://localhost:<buildHostPort>/mcp
```

Acceptable statuses:

```text
200, 400, 404, 405
```

Почему не только 200: MCP endpoint может не отвечать обычному GET как REST endpoint, но если есть HTTP-ответ, это лучше, чем connection refused.

### 16.2. Log check

Получать:

```bash
docker logs --tail <logTailLines> <container>
```

Если найден error pattern:

```text
fail infrastructure smoke-test
exit 13
```

---

## 17. MCP tool smoke-test

Модуль/утилита:

```text
mcp_smoke_test.py
```

### 17.1. Задача

Выполнить реальные MCP calls:

```text
initialize
tools/list
tools/call metadatasearch
tools/call codesearch, если indexCode=true
```

### 17.2. Рекомендуемая реализация

Использовать Python MCP SDK:

```text
mcp.client.streamable_http.streamablehttp_client
mcp.ClientSession
```

### 17.3. CLI

```powershell
python E:\mcp-1c\tools\mcp-smoke-test\mcp_smoke_test.py `
  --url http://localhost:18100/mcp `
  --timeout 7200 `
  --metadata-tool metadatasearch `
  --metadata-query-argument query `
  --metadata-query Конфигурации `
  --metadata-query Документы `
  --code-tool codesearch `
  --code-query-argument query `
  --code-query Процедура `
  --code-query Функция
```

Для удобства updater может передавать JSON config path вместо длинного CLI.

### 17.4. Tool names и argument names

Не хардкодить намертво.

Использовать config:

```json
"metadataToolName": "metadatasearch",
"metadataQueryArgument": "query",
"codeToolName": "codesearch",
"codeQueryArgument": "query"
```

Эти поля являются опциональными. Если они отсутствуют в `project.json`, использовать defaults выше. Если указаны — использовать значения из config.

Если `tools/list` не содержит нужный tool:

```text
smoke-test failed
exit 13
```

### 17.5. Success criteria

`metadatasearch` успешен, если:

```text
tool найден
tool call не вернул protocol error
результат содержит непустой content/text/result
```

`codesearch` успешен, если:

```text
indexCode=true
tool найден
хотя бы один code query вернул непустой результат
```

Если `indexCode=false`, codesearch не проверять.

### 17.6. Timeout

`timeoutSeconds` общий на весь tool smoke-test.

---

## 18. Production smoke-test

### 18.0. Implementation contract

Production smoke-test реализуется отдельной функцией, например:

```text
run_production_smoke_test(config, paths, smoke_config)
```

Функция обязана выполнить две проверки в указанном порядке:

```text
1. run_infrastructure_smoke_test(...), но с production context;
2. run_tool_smoke_test(...), если toolSmokeTest.enabled=true, но с production URL.
```

Production context:

```text
containerName = mcp.production.containerName
hostPort = mcp.production.hostPort
url = mcp.production.url
stagingPath = staging/current
chromaPath = chroma/current
```

Production infrastructure smoke-test проверяет:

```text
container exists
State.Status == running
State.Restarting == false
production hostPort доступен
production HTTP endpoint отвечает acceptableHttpStatusCodes
chroma/current существует
chroma/current не пустой, если requireChromaNotEmpty=true
production docker logs не содержит logErrorPatterns
```

Production tool smoke-test проверяет:

```text
tools/list доступен на mcp.production.url
metadatasearch найден
хотя бы один metadata query вернул непустой результат
если indexCode=true, codesearch найден
если indexCode=true, хотя бы один code query вернул непустой результат
protocol/client/tool call errors отсутствуют
```

Если production smoke-test не прошел, `switcher.py` обязан инициировать automatic rollback. `last_indexed_commit`, `current_commit` и `previous_commit` не обновляются как успешные.

Production smoke-test выполняется после switch и запуска production container. Это не одиночный ping и не только проверка контейнера: состав проверки всегда явно делится на infrastructure-уровень и, если включен `toolSmokeTest.enabled=true`, реальный MCP tool smoke-test.

Состав проверки:

```text
1. production infrastructure smoke-test;
2. MCP tool smoke-test, если toolSmokeTest.enabled=true.
```

Используются production-настройки:

```text
mcp.production.containerName
mcp.production.hostPort
mcp.production.url
staging/current
chroma/current
```

Infrastructure-часть проверяет:

```text
container exists
State.Status == running
State.Restarting == false
production hostPort доступен
production HTTP endpoint отвечает допустимым status code
production docker logs не содержит error patterns
```

Tool-часть вызывает `mcp_smoke_test.py` именно на `mcp.production.url` и использует те же tool names/query argument names, что и build smoke-test. Build URL здесь использовать запрещено.

Если production smoke-test не прошел, выполнить automatic rollback. `last_indexed_commit`, `current_commit` и `previous_commit` не записывать как успешные.

---

## 19. Switch build → current

Модуль:

```text
switcher.py
```

### 18.1. Preconditions

Switch разрешен только если:

```text
parser success
Report validation success
build container started
infrastructure smoke-test success
tool smoke-test success, если enabled
```

### 18.2. Порядок операций

```text
1. docker rm -f production container
2. remove previous dirs if exist
3. move current → previous
4. move build → current
5. move chroma/current → chroma/previous
6. move chroma/build → chroma/current
7. start production container with current volumes
8. production smoke-test: infrastructure + tool if `toolSmokeTest.enabled=true`
9. update state:
   previous_commit = old current_commit
   current_commit = target_commit
   last_indexed_commit = target_commit
```

Важный момент: порядок перемещения `staging` и `chroma` должен быть атомарно безопасным насколько возможно. Если filesystem move падает — выполнить recovery по состоянию каталогов.

### 18.3. Empty current

Если это первый запуск и `current` отсутствует:

```text
previous не создается
build становится current
production запускается
```

---

## 20. Rollback

Модуль:

```text
rollback.py
```

### 19.1. Automatic rollback

Если production smoke-test после switch упал:

```text
docker rm -f production
if rollback.preserveFailedIndex=true:
  move current → failed-<timestamp>
  move chroma/current → failed-<timestamp>
else:
  delete current
  delete chroma/current
move previous → current
move chroma/previous → current
start production
production smoke-test
last_indexed_commit не обновлять
notification rollback
```

Default:

```text
rollback.preserveFailedIndex = true
```

Если `preserveFailedIndex=true`, failed-index сохраняется для диагностики. Retention/cleanup failed-каталогов можно реализовать отдельным этапом.

### 19.2. Manual rollback

CLI:

```bash
python update_mcp_project.py --config <project.json> --rollback
```

Поведение:

```text
не делать git operations
не запускать parser
не запускать build MCP
остановить production
поменять current и previous
запустить production
проверить production smoke
не менять last_indexed_commit без отдельного будущего флага
```

---

## 21. Notifications

Модуль:

```text
notifications.py
```

### 20.1. Config

```json
"notifications": {
  "enabled": true,
  "onSuccess": false,
  "onFailure": true,
  "onRollback": true,
  "webhookUrlEnv": "MCP_UPDATE_WEBHOOK_URL"
}
```

### 20.2. Webhook payload

```json
{
  "project": "orders",
  "status": "failed",
  "stage": "mcp_tool_smoke_test",
  "targetCommit": "abc123",
  "lastIndexedCommit": "def456",
  "productionUntouched": true,
  "rollbackAttempted": false,
  "rollbackSuccess": null,
  "logPath": "E:/mcp-1c/logs/orders/20260512-103000-update.log"
}
```

### 20.3. Secret handling

Webhook URL не логировать.

Если notification failed:

```text
если update success:
  exit code 1
  статус success with warning
  production MCP остается успешным
  last_indexed_commit уже обновлен

если update уже failed:
  оставить исходный exit code ошибки update
  notification failure записать warning

если rollback выполнялся:
  оставить rollback/failure exit code
  notification failure записать warning
```

Notification failure не должен маскировать первопричину и не должен становиться hard fail после успешного production update.

---

## 22. Logging

Модуль:

```text
logging_setup.py
```

### 21.1. Main log

Файл:

```text
logsRoot/YYYYMMDD-HHMMSS-update.log
```

Содержит:

```text
project
mode: update/force/no-git-pull/rollback/dry-run
repo path
branch
target commit
last_indexed_commit
sources detected
parser command without secrets
parser exit code
Report.txt size
Docker image
build container
production container
build URL
production URL
smoke-test results
switch result
rollback result
notification result
exit code
```

### 21.2. Docker logs

```text
YYYYMMDD-HHMMSS-mcp-build.log
YYYYMMDD-HHMMSS-mcp-production.log
```

### 21.3. Secret masking

Маскировать:

```text
LICENSE_KEY
OPENAI_API_KEY, если не lm-studio/test value
MCP_UPDATE_WEBHOOK_URL
Git tokens
password
```

---

## 23. Retention

Для MVP:

```text
хранить current
хранить previous
build очищать перед каждым запуском
```

Дополнительно:

```text
keepLogsDays — можно реализовать в конце update
keepStagingBuilds — не обязательно для MVP, если build всегда один
```

---

## 24. Dry-run

`--dry-run` должен выполнять:

```text
config load
secret env check
repo check
target commit detection
source detection
state read
вывод planned actions
```

Не выполнять:

```text
git pull
parser
Docker
switch
rollback
notifications
```

Если нужен dry-run без git pull, запускать:

```text
--dry-run --no-git-pull
```

---

## 25. Tests

### 24.1. Unit tests

Обязательные тесты:

```text
config validation
source detection:
  cf only
  cfe only
  cf+cfe
  none
  required cf missing
  required cfe missing

report validation:
  valid root with leading tab
  forbidden patterns
  missing root
  empty file

state:
  no last_indexed_commit
  read/write current_commit
  read/write previous_commit

lock:
  acquire
  duplicate lock
  stale lock

switch:
  first switch without current
  switch with previous
  failed production smoke triggers rollback

notifications:
  disabled
  failure enabled
  secret URL not logged
```

### 24.2. Integration tests with fake commands

Для MVP можно mock-ать:

```text
git
docker
parser
mcp_smoke_test
```

Через wrappers/adapters, чтобы не требовать реальный Docker в unit tests.

### 24.3. Manual acceptance

На реальном проекте:

```text
1. --dry-run --no-git-pull
2. обычный запуск первый раз
3. повторный запуск без изменений
4. --force
5. --no-git-pull
6. отключить src/cf, оставить src/cfe
7. сломать Report.txt validation
8. сломать build container
9. проверить rollback
```

---

## 26. Implementation phases

### Phase 1. Skeleton

```text
CLI
config load/validate
logging
exit codes
PowerShell wrapper
```

### Phase 2. Git/source/state

```text
git_ops
source_detector
state
lock
--force
--no-git-pull
--dry-run
```

### Phase 3. Parser/staging/report

```text
prepare build dirs
generate parser-config.json
run parser
validate Report.txt
copy code/cf/cfe
```

### Phase 4. Docker/infrastructure smoke

```text
docker availability
run build container
infra smoke-test
capture docker logs
```

### Phase 5. MCP tool smoke

```text
mcp_smoke_test.py
tools/list
metadatasearch
codesearch
timeout handling
```

### Phase 6. Switch/rollback

```text
current/previous
production container start
production smoke-test
automatic rollback
manual rollback
```

### Phase 7. Notifications/retention

```text
webhook notification
secret masking
log cleanup
```

---

## 27. Acceptance criteria

### AC-001. No changes

Если `target_commit == last_indexed_commit` и нет `--force`:

```text
parser не запускается
Docker не запускается
production MCP не трогается
exit code 0
```

### AC-002. Force

Если `--force`:

```text
индексация выполняется даже для текущего commit
last_indexed_commit после успеха равен тому же commit
```

### AC-003. NoGitPull

Если `--no-git-pull`:

```text
git fetch/pull не выполняется
target_commit = HEAD
```

### AC-004. Sources

Поддерживаются:

```text
только src/cf
только src/cfe
src/cf + src/cfe
```

Если нет обоих:

```text
exit code 6
production untouched
```

### AC-005. Parser integration

Updater формирует parser-config.json с:

```text
outputPath = staging/build/metadata
diagnosticsPath = staging/build/diagnostics
logsPath = staging/build/logs
generatorSettingsPath = staging/build/settings/<project>.xml-overrides.json
```

### AC-006. Report validation

Корневая секция с ведущей табуляцией считается валидной:

```regex
^\s*-\s*Конфигурации\.
```

### AC-007. Build smoke fail

Если build MCP не прошел smoke-test:

```text
switch запрещен
production продолжает работать
last_indexed_commit не обновляется
```

### AC-008. Switch success

После успешного switch:

```text
production running
current содержит новый index
previous содержит старый index
last_indexed_commit = target_commit
```

### AC-009. Rollback

Если production smoke-test после switch упал:

```text
previous возвращается в current
production запускается на previous
last_indexed_commit не обновляется
notification отправляется
```

### AC-010. Secrets

Логи не содержат секретов.

---

## 28. Что строго запрещено

```text
1. Вносить изменения в Git repo.
2. Коммитить/пушить из updater-а.
3. Генерировать Report.txt внутри updater-а.
4. Парсить XML 1С внутри updater-а.
5. Останавливать production до успешного build smoke-test.
6. Запускать production с RESET_DATABASE=true.
7. Хранить LICENSE_KEY или webhook URL в project.json.
8. Писать секреты в лог.
9. Смешивать src/cf и src/cfe в одной папке code.
10. Считать docker logs гарантией завершения индексации.
```

---

## 29. Минимальный результат MVP

После реализации MVP должно быть возможно выполнить:

```powershell
powershell.exe -ExecutionPolicy Bypass `
  -File E:\mcp-1c\tools\mcp-project-updater\update-mcp-project.ps1 `
  -Config E:\mcp-1c\projects\orders.json
```

И получить:

```text
1. Git repo обновлен или определен текущий HEAD.
2. Если commit новый или --force:
   - создан staging/build;
   - создан Report.txt;
   - создан code/cf и/или code/cfe;
   - построен chroma/build;
   - build MCP прошел проверки;
   - production MCP переключен;
   - last_indexed_commit обновлен.
3. Если commit не изменился:
   - ничего не тронуто.
4. При ошибке:
   - production MCP не потерян;
   - rollback выполнен, если ошибка после switch;
   - есть лог и notification.
```
