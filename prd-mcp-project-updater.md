# PRD: MCP Project Updater

## 0. Authoritative config contract

Этот раздел фиксирует актуальную модель конфигурации и имеет приоритет над более ранними примерами ниже по документу.

- `project.json` содержит только проектные настройки: `project`, `repo`, `sources`, `mcp`, `paths.root`, `notifications`, `retention`, `rollback`.
- `project.json` не должен содержать `parser`, `smokeTest`, `toolSmokeTest`, `repo.path`, `paths.stagingRoot`, `paths.chromaRoot`, `paths.stateRoot`, `paths.logsRoot`, `secrets.globalFile`, `secrets.projectFile`, `OPENAI_API_BASE`, `OPENAI_MODEL`.
- Все общие настройки parser/smoke/embedding лежат в `<paths.root.parent>/settings.global.json`.
- `settings.global.json` содержит `parser`, `mcp.env`, `mcp.secretEnv`, `smokeTest`, `smokeTest.toolSmokeTest`.
- `settings.smokeTest.toolSmokeTest.url` запрещен: build smoke использует `mcp.build.url`, production smoke использует `mcp.production.url`.
- Секреты читаются из `<paths.root.parent>/secrets.global.json` и `<paths.root>/secrets.local.json`; переменные окружения процесса для `GITLAB_TOKEN`, `LICENSE_KEY`, `OPENROUTER_API_KEY`, `MCP_UPDATE_WEBHOOK_URL` не являются источником конфигурации.
- Локальный Git checkout всегда `<paths.root>/repo`; staging/chroma/state/logs всегда `<paths.root>/staging`, `<paths.root>/chroma`, `<paths.root>/state`, `<paths.root>/logs`.
- Разрешенные MCP images: `comol/1c_code_metadata_mcp:light` и `comol/1c_code_metadata_mcp:latest`.

## 1. Название

**MCP Project Updater**

Рабочие компоненты:

```text
update_mcp_project.py      — основная кроссплатформенная логика updater-а
update-mcp-project.ps1     — тонкая Windows-обертка для Task Scheduler
mcp_smoke_test.py          — отдельная утилита проверки MCP tools
generate_config_report.py  — готовый parser Report.txt
```

## 2. Контекст

Есть MCP `CodeMetadataSearchServer`, который индексирует:

```text
metadata/Report.txt — отчет по метаданным 1С для metadatasearch
code/               — XML/BSL-выгрузку 1С для codesearch
chroma_db/          — векторную базу MCP
```

Описание `CodeMetadataSearchServer` фиксирует, что контейнер использует внутренний порт `8000`, endpoint в `mcp.json` имеет вид `http://localhost:8000/mcp`, а том `/app/chroma_db` обязателен, иначе при каждом перезапуске будет повторная индексация. Также указано, что первая индексация может занимать несколько часов.

Парсер `generate-config-report` уже готовится как отдельный компонент. Он формирует `Report.txt` по XML-выгрузке 1С, поддерживает project config, diagnostics, logs, `warningsAsErrors`, `buildXmlOverrides`, `generatorSettingsPath`, а также сценарии с основной конфигурацией и/или расширением.

Целевая цепочка:

```text
Git repo
  ↓
update_mcp_project.py
  ↓
git fetch / pull или текущий HEAD
  ↓
staging/build
  ↓
generate-config-report
  ↓
metadata/Report.txt + code/
  ↓
MCP build container
  ↓
infrastructure smoke-test
  ↓
MCP tool smoke-test
  ↓
switch build → current
  ↓
production MCP
  ↓
last_indexed_commit update
```

## 3. Главная цель

Разработать **MCP Project Updater** — автоматизатор обновления MCP-индекса проекта 1С из Git-репозитория.

Updater должен безопасно:

```text
1. Проверять наличие изменений в Git.
2. Подготавливать staging-каталог.
3. Запускать готовый parser generate-config-report.
4. Подготавливать CODE_PATH для MCP.
5. Запускать build MCP-контейнер на отдельном порту.
6. Проверять готовность build MCP.
7. Выполнять реальный MCP tool smoke-test, если включен.
8. Переключать production MCP только после успешных проверок.
9. Хранить last_indexed_commit.
10. Поддерживать rollback.
11. Отправлять уведомления при ошибках и rollback.
```

## 4. Архитектурное решение

PowerShell **не является ядром системы**.

Правильная архитектура:

```text
Windows Task Scheduler
  ↓
update-mcp-project.ps1
  ↓
python update_mcp_project.py --config <project.json>
```

В будущем на Linux:

```text
cron/systemd
  ↓
python3 update_mcp_project.py --config <project.json>
```

`update-mcp-project.ps1` — только тонкая обертка, которая передает параметры в Python updater и возвращает exit code.

## 5. Почему не Jenkins/GitLab CI Runner в MVP

На первом этапе Jenkins и GitLab CI Runner не используются.

MVP запускается через:

```text
Windows Task Scheduler
```

Причины:

```text
1. Сейчас рабочая машина Windows.
2. Нужно быстрее довести локальную автоматизацию MCP.
3. Не хочется добавлять отдельный CI/CD слой до стабилизации updater-а.
4. Ядро на Python сохранит возможность будущего переноса в Jenkins, GitLab CI Runner, cron или systemd.
```

## 6. Поддерживаемые режимы проекта

Updater должен поддерживать три валидных режима.

### 6.1. Только основная конфигурация

```text
src\cf  есть
src\cfe нет
```

Результат:

```text
Report.txt содержит только основную конфигурацию
code/ содержит cf
```

### 6.2. Основная конфигурация + расширение

```text
src\cf  есть
src\cfe есть
```

Результат:

```text
Report.txt содержит две корневые секции:
- Конфигурации.<ИмяОсновнойКонфигурации>
- Конфигурации.<ИмяРасширения>

code/ содержит cf и cfe
```

### 6.3. Только расширение

```text
src\cf  нет
src\cfe есть
```

Результат:

```text
Report.txt содержит только расширение
code/ содержит cfe
```

### 6.4. Недопустимый режим

```text
src\cf  нет
src\cfe нет
```

Результат:

```text
ошибка
MCP не переиндексируется
production MCP не трогается
last_indexed_commit не обновляется
```

## 7. Вне области продукта

Updater не должен:

```text
1. Парсить XML 1С самостоятельно.
2. Формировать Report.txt самостоятельно.
3. Анализировать BSL.
4. Исправлять ошибки parser-а.
5. Менять структуру Git-репозитория.
6. Коммитить изменения в Git.
7. Пушить изменения в Git.
8. Запускать Конфигуратор 1С.
9. Загружать конфигурацию в ИБ.
10. Выполнять синтаксическую проверку 1С.
11. Управлять Jenkins/GitLab CI Runner.
```

## 8. Среда выполнения MVP

```text
Windows 10/11 или Windows Server
PowerShell 5.1+ или PowerShell 7+
Python 3.11+
Git for Windows
Docker Desktop или Docker Engine
локальный clone Git-репозитория
готовый generate-config-report
```

## 9. Структура каталогов

Актуальная структура разделяет:

- installation root updater-а — каталог, из которого запускается `update_mcp_project.py`;
- data root — каталог данных всех MCP-проектов;
- project root — `paths.root` конкретного проекта внутри data root.

Пример:

```text
C:\Work\MCP updater\mcp-project-updater\
  update_mcp_project.py
  update-mcp-project.ps1
  mcp_smoke_test.py

C:\tools\onec\
  generate_config_report.py

C:\mcp-updater-data\
  settings.global.json
  secrets.global.json

  orders\
    project.json
    secrets.local.json

    repo\
      .git\
      src\
        cf\
        cfe\

    staging\
      build\
        metadata\
          Report.txt
        code\
          cf\
          cfe\
        diagnostics\
          report-stats.json
          report-diagnostics.json
        logs\
        settings\
          orders.xml-overrides.json
        parser-config.json

      current\
        metadata\
          Report.txt
        code\
          cf\
          cfe\
        diagnostics\
        logs\
        settings\

      previous\

    chroma\
      build\
      current\
      previous\

    state\
      last_indexed_commit
      current_commit
      previous_commit
      last_source_fingerprint
      last_report_hash
      lock

    logs\
      20260512-103000-update.log
      20260512-103000-mcp-build.log
      20260512-103000-mcp-production.log
```

Для этого примера:

```json
{
  "paths": {
    "root": "C:/mcp-updater-data/orders"
  }
}
```

Derived paths:

```text
repo.path    = <paths.root>/repo
stagingRoot  = <paths.root>/staging
chromaRoot   = <paths.root>/chroma
stateRoot    = <paths.root>/state
logsRoot     = <paths.root>/logs
global config = <paths.root.parent>/settings.global.json
global secrets = <paths.root.parent>/secrets.global.json
project secrets = <paths.root>/secrets.local.json
```

Запрещено задавать эти derived paths отдельными полями в `project.json`.

## 10. Project config

`project.json` содержит только проектные параметры.

Пример `C:/mcp-updater-data/orders/project.json`:

```json
{
  "project": "orders",
  "repo": {
    "branch": "master",
    "remote": "origin",
    "pullMode": "ff-only",
    "cloneUrl": "https://gitlab.example.com/team/orders.git",
    "auth": {
      "type": "gitlab-token",
      "tokenSecret": "GITLAB_TOKEN",
      "username": "oauth2"
    }
  },
  "sources": {
    "mainConfigPath": "src/cf",
    "mainConfigRequired": true,
    "extensionPath": "src/cfe",
    "extensionRequired": false
  },
  "mcp": {
    "image": "comol/1c_code_metadata_mcp:light",
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
    "useGpu": false
  },
  "paths": {
    "root": "C:/mcp-updater-data/orders"
  },
  "notifications": {
    "enabled": true,
    "onSuccess": false,
    "onFailure": true,
    "onRollback": true,
    "webhookUrlSecret": "MCP_UPDATE_WEBHOOK_URL"
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

Общие настройки для всех проектов лежат в `C:/mcp-updater-data/settings.global.json`:

```json
{
  "parser": {
    "toolPath": "C:/tools/onec/generate_config_report.py",
    "encoding": "utf-8",
    "warningsAsErrors": false,
    "buildXmlOverrides": true,
    "allowedExitCodes": [0, 1]
  },
  "mcp": {
    "env": {
      "OPENAI_API_BASE": "https://openrouter.ai/api/v1",
      "OPENAI_MODEL": "qwen/qwen3-embedding-8b"
    },
    "secretEnv": {
      "LICENSE_KEY": "ONERPA_LICENSE_KEY",
      "OPENAI_API_KEY": "OPENROUTER_API_KEY"
    }
  },
  "smokeTest": {
    "enabled": true,
    "profile": "production",
    "reportValidation": {
      "enabled": true,
      "requiredReportPatterns": [
        "Имя: \"",
        "Синоним: \""
      ],
      "forbiddenReportPatterns": []
    },
    "infrastructure": {
      "enabled": true,
      "timeoutSeconds": 120,
      "checkIntervalSeconds": 5,
      "acceptableHttpStatusCodes": [200, 400, 404, 405],
      "requireChromaNotEmpty": true,
      "logTailLines": 200,
      "logErrorPatterns": [
        "Traceback",
        "Unhandled exception",
        "CRITICAL"
      ],
      "logReadyPatterns": [
        "Started",
        "Application startup complete"
      ]
    },
    "toolSmokeTest": {
      "enabled": true,
      "toolPath": "C:/im/Devops/MCP Updater/mcp_smoke_test.py",
      "timeoutSeconds": 54000,
      "attemptTimeoutSeconds": 60,
      "retryIntervalSeconds": 30,
      "diagnostic": false,
      "metadataToolName": "metadatasearch",
      "metadataQueryArgument": "query",
      "metadataQueries": [
        "Конфигурации"
      ],
      "codeToolName": "codesearch",
      "codeQueryArgument": "query",
      "codeQueries": [
        "Процедура"
      ]
    }
  }
}
```

`settings.smokeTest.toolSmokeTest.url` запрещен. Build URL берется из `project.json -> mcp.build.url`, production URL берется из `project.json -> mcp.production.url`.

Секреты лежат отдельно:

```text
C:/mcp-updater-data/secrets.global.json
C:/mcp-updater-data/orders/secrets.local.json
```

## 11. Порты и endpoint

Внутри контейнера MCP использует порт:

```text
8000
```

Для каждого проекта на host назначается свой порт.

Пример:

```text
orders production: http://localhost:8100/mcp
orders build:      http://localhost:18100/mcp

zup production:    http://localhost:8200/mcp
zup build:         http://localhost:18200/mcp

upp production:    http://localhost:8300/mcp
upp build:         http://localhost:18300/mcp
```

Docker port mapping:

```text
production: -p 8100:8000
build:      -p 18100:8000
```

## 12. Секреты

Секреты не должны храниться в `project.json`.

```json
"secretEnv": {
  "LICENSE_KEY": "ONERPA_LICENSE_KEY"
}
```

Это означает:

```text
переменная контейнера LICENSE_KEY берется из переменной окружения ONERPA_LICENSE_KEY
```

Если обязательная переменная окружения отсутствует:

```text
updater завершается ошибкой до запуска Docker
```

Логи не должны содержать значения:

```text
LICENSE_KEY
OPENAI_API_KEY, если это реальный секрет
Git tokens
пароли
webhook URL
```

## 13. CLI updater-а

Основной запуск:

```powershell
python E:\mcp-1c\tools\mcp-project-updater\update_mcp_project.py `
  --config E:\mcp-1c\projects\orders.json
```

Через PowerShell wrapper:

```powershell
powershell.exe -ExecutionPolicy Bypass `
  -File E:\mcp-1c\tools\mcp-project-updater\update-mcp-project.ps1 `
  -Config E:\mcp-1c\projects\orders.json
```

### 13.1. CLI options

```text
--config <path>       путь к project.json
--force               переиндексировать текущий commit даже без изменений
--no-git-pull         не делать git fetch/pull, использовать текущий HEAD
--rollback            выполнить ручной rollback current ↔ previous
--verbose             подробный лог
--dry-run             проверить config/source/state без запуска parser/Docker
```

PowerShell wrapper должен поддерживать аналогичные параметры:

```powershell
update-mcp-project.ps1 -Config <path> [-Force] [-NoGitPull] [-Rollback] [-Verbose] [-DryRun]
```

## 14. Значение `--force`

Обычная логика:

```text
target_commit == last_indexed_commit
→ изменений нет
→ переиндексация не выполняется
```

`--force` меняет поведение:

```text
target_commit == last_indexed_commit
→ все равно выполнить parser
→ пересобрать staging
→ пересобрать MCP index
→ после успеха оставить last_indexed_commit тем же commit
```

`--force` нужен, если:

```text
1. поменялся parser;
2. поменялись настройки MCP;
3. поменялась embedding model;
4. повредился chroma/current;
5. нужно руками пересобрать индекс без нового commit.
```

## 15. Значение `--no-git-pull`

Обычный режим:

```text
git fetch
git pull --ff-only
target_commit = origin/<branch>
```

Режим `--no-git-pull`:

```text
git fetch/pull не выполняется
target_commit = текущий HEAD локальной рабочей копии
```

Нужен для:

```text
1. ручной отладки;
2. тестирования локального checkout;
3. будущей интеграции с другим runner;
4. ситуаций, когда repo уже обновлен внешним процессом.
```

Даже в режиме `--no-git-pull` updater должен проверять отсутствие tracked changes, если не введен отдельный режим `--allow-dirty`.

`--allow-dirty` в MVP не входит.

## 16. Workflow

### 16.1. Happy path

```text
1. Прочитать project.json.
2. Проверить lock.
3. Проверить обязательные secret env.
4. Проверить Git repository.
5. Если не --no-git-pull:
   - git fetch
   - git checkout <branch>
   - git pull --ff-only
   - target_commit = origin/<branch>
6. Если --no-git-pull:
   - target_commit = HEAD
7. Сравнить target_commit с last_indexed_commit.
8. Если commit совпадает и нет --force:
   - записать "no changes"
   - завершиться с exit code 0.
9. Проверить источники src/cf и src/cfe.
10. Если нет ни одного источника — ошибка.
11. Очистить staging/build.
12. Создать staging/build:
    - metadata
    - code
    - diagnostics
    - logs
    - settings
13. Сформировать parser-config.json.
14. Запустить generate-config-report.
15. Проверить Report.txt.
16. Скопировать доступные источники:
    - src/cf  → build/code/cf
    - src/cfe → build/code/cfe
17. Очистить chroma/build.
18. Запустить MCP build container.
19. Выполнить infrastructure smoke-test.
20. Выполнить MCP tool smoke-test, если включен.
21. Если проверки успешны — разрешить switch.
22. Остановить production MCP.
23. Переместить current → previous.
24. Переместить build → current.
25. Запустить production MCP на production.url/hostPort.
26. Проверить production smoke-test: production infrastructure smoke-test + MCP tool smoke-test, если `toolSmokeTest.enabled=true`.
27. Обновить last_indexed_commit.
28. Отправить уведомление, если настроено.
29. Снять lock.
30. Завершиться успешно.
```

### 16.2. No changes path

Если `target_commit == last_indexed_commit` и `--force` не передан:

```text
1. Parser не запускается.
2. Docker build не запускается.
3. Production MCP не трогается.
4. Exit code 0.
```

### 16.3. Failed build path

Если parser, Report validation, MCP build или smoke-test упали:

```text
1. Production MCP не трогается.
2. last_indexed_commit не обновляется.
3. build container останавливается.
4. build artifacts сохраняются для диагностики.
5. Отправляется failure notification, если включено.
6. Exit code по типу ошибки.
```

### 16.4. Bootstrap path

Если это первый production deploy и рабочий MCP еще не существует:

```text
1. Допустимо, что локальный repo еще не клонирован.
2. Допустимо, что current/previous artifacts еще отсутствуют.
3. Допустимо, что production container еще отсутствует.
4. Updater должен выполнить обычный build pipeline.
5. При успешном switch:
   - build → current;
   - chroma/build → chroma/current;
   - current_commit = target_commit;
   - last_indexed_commit = target_commit;
   - previous_commit не заполняется, пока не появится следующий успешный baseline.
6. Если самый первый production smoke-test после switch упал:
   - automatic rollback восстановить нечего, так как previous baseline отсутствует;
   - updater завершает workflow как rollback failed;
   - требуется ручное вмешательство оператора.
```

## 17. Git requirements

### FR-001. Проверка Git repository

Updater должен проверить:

```text
repo.path существует
внутри есть .git
branch доступна
рабочее дерево не содержит tracked changes
```

Если есть tracked changes:

```text
ошибка
production MCP не трогается
```

### FR-002. Получение target commit

Обычный режим:

```powershell
git fetch <remote> <branch>
git checkout <branch>
git pull --ff-only <remote> <branch>
git rev-parse <remote>/<branch>
```

Режим `--no-git-pull`:

```powershell
git rev-parse HEAD
```

### FR-003. last_indexed_commit

Файл:

```text
state/last_indexed_commit
```

Если файла нет:

```text
считать, что проект еще не индексировался
выполнить полную индексацию
```

Обновлять файл можно только после успешного production smoke-test.

## 18. Source requirements

### FR-004. Проверка источников

С учетом config:

```text
mainConfigPath
mainConfigRequired
extensionPath
extensionRequired
```

Правила:

```text
src/cf отсутствует, mainConfigRequired=true
→ ошибка

src/cfe отсутствует, extensionRequired=true
→ ошибка

src/cf отсутствует и src/cfe отсутствует
→ ошибка

src/cf есть или src/cfe есть
→ продолжить
```

### FR-005. Подготовка CODE_PATH

Updater должен собрать `build/code` только из существующих источников:

```text
repo/src/cf  → staging/build/code/cf
repo/src/cfe → staging/build/code/cfe
```

Запрещено:

```text
смешивать cf и cfe
переименовывать объекты
изменять файлы выгрузки
исключать XML/BSL без явной настройки
```

## 19. Parser integration

### FR-006. Генерация parser-config.json

Updater должен генерировать parser config в:

```text
staging/build/parser-config.json
```

Пример:

```json
{
  "project": "orders",
  "repoPath": "E:/mcp-1c/repos/orders",

  "mainConfigPath": "src/cf",
  "mainConfigRequired": false,

  "extensionPath": "src/cfe",
  "extensionRequired": false,

  "outputPath": "E:/mcp-1c/staging/orders/build/metadata",
  "reportFileName": "Report.txt",

  "diagnosticsPath": "E:/mcp-1c/staging/orders/build/diagnostics",
  "logsPath": "E:/mcp-1c/staging/orders/build/logs",

  "encoding": "utf-8",
  "warningsAsErrors": false,

  "buildXmlOverrides": true,
  "generatorSettingsPath": "E:/mcp-1c/staging/orders/build/settings/orders.xml-overrides.json"
}
```

### FR-007. generatorSettingsPath обязателен для updater-а

Если `buildXmlOverrides=true`, updater должен всегда задавать `generatorSettingsPath` внутри `staging/build/settings`.

Причина: parser умеет создавать generated overrides внутри папки инструмента, если путь не задан, но для автоматического updater-а это нежелательно: build должен быть самодостаточным, а tool directory не должен модифицироваться.

### FR-008. Запуск parser-а

Команда:

```powershell
python <parser.toolPath> --config <staging/build/parser-config.json>
```

Допустимые exit codes:

```json
"allowedExitCodes": [0, 1]
```

Если parser вернул код не из списка:

```text
MCP build не запускается
production MCP не трогается
last_indexed_commit не обновляется
```

## 20. Report validation

### FR-009. Проверка Report.txt

Updater должен проверить:

```text
1. Report.txt существует.
2. Размер > 0.
3. Есть хотя бы одна корневая секция.
4. Есть базовые свойства.
5. Нет запрещенных технических паттернов.
6. diagnostics/errors = 0, если diagnostics доступны.
```

Корневой regex:

```regex
^\s*-\s*Конфигурации\.
```

Это важно, потому что parser формирует корневую секцию с табуляцией перед `-`.

## 21. Docker/MCP build

### FR-010. Запуск build container

Build container запускается отдельно от production:

```text
containerName = mcp.build.containerName
hostPort = mcp.build.hostPort
containerPort = mcp.containerPort
metadata = staging/build/metadata
code = staging/build/code
chroma = chroma/build
RESET_DATABASE=true
```

Docker mapping:

```powershell
-p <build.hostPort>:<containerPort>
```

Пример:

```powershell
-p 18100:8000
```

### FR-011. Environment variables

Updater должен передавать:

```text
LICENSE_KEY
METADATA_PATH=/app/metadata
CODE_PATH=/app/code
RESET_DATABASE=true
RESET_CACHE=false
USESSE=false
OPENAI_API_BASE
OPENAI_API_KEY
OPENAI_MODEL
```

Если `useGpu=true`:

```text
добавить --gpus all
```

## 22. Smoke-test

Smoke-test делится на два уровня:

```text
1. Infrastructure smoke-test
2. MCP tool smoke-test
```

### FR-012. Infrastructure smoke-test

Build MCP считается инфраструктурно готовым, если:

```text
1. build container exists.
2. build container running.
3. build container не restart loop.
4. buildPort доступен.
5. HTTP endpoint отвечает допустимым статус-кодом.
6. chroma/build существует.
7. chroma/build не пустой, если requireChromaNotEmpty=true.
8. В последних N строках docker logs нет error patterns.
9. Готовность достигнута до timeout.
```

Infrastructure smoke-test не доказывает качество индекса.

### FR-013. MCP tool smoke-test

Если `toolSmokeTest.enabled=true`, updater запускает:

```powershell
python E:\mcp-1c\tools\mcp-smoke-test\mcp_smoke_test.py `
  --url http://localhost:18100/mcp `
  --timeout 7200
```

Утилита должна выполнить реальные MCP-запросы:

```text
tools/list
tools/call metadatasearch
tools/call codesearch, если INDEX_CODE=true
```

Минимальные проверки:

```text
metadatasearch существует
metadatasearch возвращает непустой результат
codesearch существует, если indexCode=true
codesearch возвращает непустой результат хотя бы на один query
ошибок protocol/client/tool call нет
```

Поля имен инструментов и аргументов являются опциональными. Если они не указаны в `project.json`, использовать defaults:

```json
{
  "metadataToolName": "metadatasearch",
  "metadataQueryArgument": "query",
  "codeToolName": "codesearch",
  "codeQueryArgument": "query"
}
```

Если поля указаны в `project.json`, updater и `mcp_smoke_test.py` должны использовать значения из config.

### FR-014. Готовность индекса

Не считать Docker logs гарантией завершения индексации.

Правило:

```text
Логи — диагностика.
Готовность индекса для switch подтверждается успешным MCP tool smoke-test.
```

Политика задается через `smokeTest.profile`:

```text
profile=dev:
  toolSmokeTest.enabled=false разрешен, но updater обязан записать warning:
  "MCP tool smoke-test skipped"

profile=production:
  toolSmokeTest.enabled=false запрещен.
  Это ошибка config validation, updater завершается с exit code 2.
```

Если `profile` не указан, использовать default `dev`. Для реальной эксплуатации рекомендуется `profile=production` и `toolSmokeTest.enabled=true`.

### FR-014A. Production smoke-test: состав проверки

Production smoke-test — это отдельная обязательная проверка после switch и запуска production container. Его состав определяется явно и не должен трактоваться как один ping или только проверка Docker-статуса.

Production smoke-test состоит из двух частей:

```text
1. Production infrastructure smoke-test — всегда обязателен.
2. Production MCP tool smoke-test — обязателен, если toolSmokeTest.enabled=true.
```

#### Production infrastructure smoke-test

Проверка выполняется на production-настройках из config:

```text
mcp.production.containerName
mcp.production.hostPort
mcp.production.url
staging/current
chroma/current
```

Минимальный состав проверки:

```text
1. production container существует;
2. production container имеет State.Status=running;
3. production container не находится в restart loop;
4. production hostPort доступен;
5. production HTTP endpoint отвечает одним из acceptableHttpStatusCodes;
6. chroma/current существует;
7. chroma/current не пустой, если requireChromaNotEmpty=true;
8. docker logs production container не содержат logErrorPatterns.
```

#### Production MCP tool smoke-test

Если `toolSmokeTest.enabled=true`, updater обязан выполнить `mcp_smoke_test.py` на `mcp.production.url`, а не на build URL.

Проверки:

```text
1. tools/list доступен;
2. metadatasearch найден;
3. хотя бы один metadata query вернул непустой результат;
4. если mcp.indexCode=true, codesearch найден;
5. если mcp.indexCode=true, хотя бы один code query вернул непустой результат;
6. protocol/client/tool call errors отсутствуют.
```

Если любая часть production smoke-test не пройдена:

```text
1. last_indexed_commit не обновляется;
2. updater выполняет automatic rollback;
3. итоговый exit code = 15, если rollback успешен;
4. итоговый exit code = 16, если rollback также неуспешен.
```

## 23. Switch build → current

### FR-015. Условия switch

Switch разрешен только если:

```text
1. Git update успешен.
2. Найден хотя бы один источник src/cf или src/cfe.
3. Parser завершился с допустимым exit code.
4. Report.txt прошел validation.
5. Build MCP прошел infrastructure smoke-test.
6. MCP tool smoke-test прошел успешно, если включен.
```

### FR-016. Порядок switch

```text
1. Остановить production container.
2. Переместить chroma/current → chroma/previous.
3. Переместить staging/current → staging/previous.
4. Переместить chroma/build → chroma/current.
5. Переместить staging/build → staging/current.
6. Запустить production container.
7. Выполнить production smoke-test: production infrastructure smoke-test + MCP tool smoke-test, если `toolSmokeTest.enabled=true`.
8. Обновить last_indexed_commit.
```

### FR-017. Production smoke-test после switch

Production smoke-test после switch выполняется строго по составу, описанному в `FR-014A. Production smoke-test: состав проверки`. Это обязательный gate перед обновлением `last_indexed_commit`. Повторно: это не один абстрактный ping, а production infrastructure smoke-test и, при включенном `toolSmokeTest.enabled=true`, реальный MCP tool smoke-test:

```text
1. production infrastructure smoke-test;
2. MCP tool smoke-test, если toolSmokeTest.enabled=true.
```

Проверяются production-настройки:

```text
production.containerName
production.hostPort
production.url
chroma/current
staging/current
```

Минимальный состав production infrastructure smoke-test:

```text
1. production container running;
2. production container не находится в restart loop;
3. production hostPort доступен;
4. production HTTP endpoint отвечает допустимым статус-кодом;
5. docker logs не содержат critical error patterns.
```

Если `toolSmokeTest.enabled=true`, дополнительно выполняются реальные MCP-вызовы к production URL:

```text
metadatasearch
codesearch, если indexCode=true
```

Если production smoke-test не пройден, updater обязан выполнить automatic rollback и не обновлять `last_indexed_commit`.

## 24. Rollback

### FR-018. Автоматический rollback

Если production smoke-test после switch провалился:

```text
1. Остановить неуспешный production container.
2. Если rollback.preserveFailedIndex=true:
   - переместить неудачный current в failed-<timestamp>;
   - переместить chroma/current в failed-<timestamp>.
3. Если rollback.preserveFailedIndex=false:
   - удалить неудачный current/chroma current.
4. Вернуть previous → current.
5. Запустить production container.
6. Проверить production smoke-test.
7. last_indexed_commit не обновлять.
8. Отправить rollback notification.
9. Завершиться ошибкой.
```

Default:

```text
rollback.preserveFailedIndex = true
```

Сохранение failed-index нужно для диагностики: можно посмотреть неудачный `Report.txt`, `code/`, `chroma_db` и Docker logs.

Automatic rollback требует существующего `previous` baseline. Если это самый первый production deploy и `previous` artifacts еще не существуют, automatic rollback невозможен и workflow завершается статусом `rollback failed`.

### FR-019. Ручной rollback

Команда:

```powershell
python update_mcp_project.py --config E:\mcp-1c\projects\orders.json --rollback
```

или wrapper:

```powershell
update-mcp-project.ps1 -Config E:\mcp-1c\projects\orders.json -Rollback
```

Ручной rollback:

```text
не делает git pull
не запускает parser
не строит новый index
меняет current и previous
перезапускает production MCP
```

Ручной rollback возможен только если уже существуют обе версии: `current` и `previous`, а также записаны `current_commit` и `previous_commit`.

## 25. Locking

### FR-020. Lock-файл

Файл:

```text
state/lock
```

Содержимое:

```json
{
  "pid": 1234,
  "startedAt": "2026-05-12T10:30:00",
  "project": "orders"
}
```

Если lock существует:

```text
если процесс жив — завершиться с ошибкой
если процесс не жив и lock stale — заменить
если невозможно проверить — завершиться с ошибкой
```

Lock должен сниматься в `finally`.

## 26. Logging

### FR-021. Лог updater-а

На каждый запуск:

```text
logsRoot/YYYYMMDD-HHMMSS-update.log
```

Лог должен содержать:

```text
project
repo path
branch
target commit
last_indexed_commit
режим --force
режим --no-git-pull
наличие src/cf
наличие src/cfe
parser exit code
размер Report.txt
Docker image
production URL
build URL
результат infrastructure smoke-test
результат tool smoke-test
switch status
rollback status
notification status
exit code
```

### FR-022. Docker logs

Сохранять:

```text
logsRoot/YYYYMMDD-HHMMSS-mcp-build.log
logsRoot/YYYYMMDD-HHMMSS-mcp-production.log
```

## 27. Notifications

### FR-023. Webhook notifications

Config:

```json
"notifications": {
  "enabled": true,
  "onSuccess": false,
  "onFailure": true,
  "onRollback": true,
  "webhookUrlSecret": "MCP_UPDATE_WEBHOOK_URL"
}
```

Webhook URL берется только из secrets files по имени секрета `notifications.webhookUrlSecret`.

Сообщение должно содержать:

```text
project
status
stage
target_commit
last_indexed_commit
production untouched true/false
rollback attempted true/false
rollback success true/false
log path
```

### FR-024. Политика ошибок уведомлений

Ошибка отправки уведомления не должна маскировать результат основного update/rollback.

```text
notification failed после успешного update:
  exit code 1
  статус: success with warning
  production MCP остается успешным
  last_indexed_commit уже обновлен

notification failed после failed update:
  сохраняется исходный exit code ошибки update
  notification failure пишется в лог как дополнительный warning

notification failed после rollback:
  сохраняется exit code rollback/failure
  notification failure пишется в лог как дополнительный warning
```

`notification failed` не является самостоятельным hard fail для уже успешного обновления MCP.

По умолчанию:

```text
onFailure = true
onRollback = true
onSuccess = false
```

## 28. Exit codes

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

Если уведомление не отправилось после успешного update, updater должен завершиться с exit code 1. Если уведомление не отправилось после уже возникшей ошибки, updater должен сохранить исходный exit code ошибки.

Код `20` не используется в основном workflow. Ошибка notification не имеет отдельного hard-fail exit code и не должна маскировать результат update/rollback.

## 29. Scheduling

MVP запускается через Windows Task Scheduler.

Пример:

```powershell
powershell.exe -ExecutionPolicy Bypass `
  -File E:\mcp-1c\tools\mcp-project-updater\update-mcp-project.ps1 `
  -Config E:\mcp-1c\projects\orders.json
```

Рекомендуемая частота:

```text
каждый час
```

Если индексация тяжелая:

```text
отдельный режим расписания:
- частая проверка Git
- реальная переиндексация ночью
```

В MVP это можно решить расписанием Task Scheduler, не логикой updater-а.

## 30. MVP

### Входит в MVP

```text
1. update_mcp_project.py как ядро.
2. update-mcp-project.ps1 как wrapper.
3. Чтение project.json.
4. Lock-файл.
5. Git fetch/pull ff-only.
6. --force.
7. --no-git-pull.
8. Проверка last_indexed_commit.
9. Поддержка:
   - только src/cf;
   - src/cf + src/cfe;
   - только src/cfe.
10. Подготовка staging/build.
11. Генерация parser-config.json.
12. Запуск parser-а.
13. Report validation.
14. Подготовка code/cf и code/cfe.
15. Запуск MCP build container.
16. Infrastructure smoke-test.
17. MCP tool smoke-test через mcp_smoke_test.py.
18. Switch build → current.
19. Production smoke-test.
20. Rollback.
21. Notifications на failure/rollback.
22. Exit codes.
23. Логи.
```

### Не входит в MVP

```text
1. Jenkins.
2. GitLab CI Runner.
3. Linux deployment.
4. Web UI.
5. Prometheus metrics.
6. Поддержка нескольких расширений.
7. Поддержка нескольких веток одновременно.
8. Автоматическое создание Git clone.
9. Автоматическая установка Docker/Python/Git.
10. Telegram/email bot как отдельная интеграция.
```

## 31. Критерии приемки

### AC-001. Нет изменений

Если `target_commit == last_indexed_commit` и нет `--force`:

```text
parser не запускается
Docker build не запускается
production MCP не трогается
exit code 0
```

### AC-002. Force rebuild

Если передан `--force`:

```text
переиндексация выполняется даже при совпадении commit
last_indexed_commit после успеха остается тем же commit
```

### AC-003. NoGitPull

Если передан `--no-git-pull`:

```text
git fetch/pull не выполняется
target_commit = HEAD
остальная логика работает штатно
```

### AC-004. Только src/cf

Updater успешно строит:

```text
staging/current/metadata/Report.txt
staging/current/code/cf
```

### AC-005. src/cf + src/cfe

Updater успешно строит:

```text
staging/current/code/cf
staging/current/code/cfe
```

### AC-006. Только src/cfe

Updater успешно строит:

```text
staging/current/metadata/Report.txt
staging/current/code/cfe
```

### AC-007. Нет источников

Если нет ни `src/cf`, ни `src/cfe`:

```text
exit code 6
production MCP не трогается
```

### AC-008. Parser failed

Если parser вернул недопустимый код:

```text
MCP build не запускается
production MCP не трогается
last_indexed_commit не обновляется
```

### AC-009. Report validation failed

Если `Report.txt` не прошел проверку:

```text
MCP build не запускается
production MCP не трогается
```

### AC-010. Build MCP smoke failed

Если build MCP не прошел infrastructure или tool smoke-test:

```text
switch запрещен
production MCP продолжает работать
last_indexed_commit не обновляется
```

### AC-011. Switch success

После успешного switch:

```text
production MCP running
last_indexed_commit = target_commit
current содержит новый индекс
previous содержит старый индекс
```

### AC-012. Switch failed

Если production MCP не прошел smoke-test:

```text
rollback выполнен
last_indexed_commit не обновлен
notification отправлена
```

### AC-013. Секреты не пишутся в лог

Логи не содержат:

```text
LICENSE_KEY
OPENAI_API_KEY
Git tokens
webhook URL
пароли
```

## 32. Рекомендуемые defaults

```text
pullMode = ff-only
mainConfigRequired = false
extensionRequired = false
parser.allowedExitCodes = [0, 1]
parser.buildXmlOverrides = true
mcp.containerPort = 8000
mcp.indexCode = true
mcp.indexMetadata = true
mcp.indexHelp = false
mcp.resetDatabaseOnBuild = true
mcp.resetCache = false
mcp.useSse = false
smokeTest.reportValidation.enabled = true
smokeTest.infrastructure.enabled = true
smokeTest.profile = dev
smokeTest.toolSmokeTest.enabled = true
notifications.onSuccess = false
notifications.onFailure = true
notifications.onRollback = true
rollback.preserveFailedIndex = true
keepPreviousIndexes = 1
```

Для production-эксплуатации рекомендуется:

```text
smokeTest.profile = production
smokeTest.toolSmokeTest.enabled = true
```

## 33. Итоговая формулировка задачи

Разработать **MCP Project Updater** — кроссплатформенное Python-ядро `update_mcp_project.py` и тонкую Windows-обертку `update-mcp-project.ps1` для автоматического обновления MCP-индекса проекта 1С из Git.

Updater должен поддерживать проекты:

```text
только src/cf
src/cf + src/cfe
только src/cfe
```

Должен существовать хотя бы один источник:

```text
src/cf или src/cfe
```

Updater отвечает за:

```text
Git update
staging/build
запуск готового generate-config-report
подготовку CODE_PATH
запуск MCP build container
infrastructure smoke-test
MCP tool smoke-test
switch build → current
production MCP restart
rollback
notifications
state management
```

Production MCP не должен останавливаться и не должен терять рабочий индекс, пока новый индекс не построен и не прошел обязательные проверки.
