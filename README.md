# MCP Project Updater

`mcp-project-updater` обновляет MCP-индексы 1C-проектов из Git: собирает `Report.txt`, готовит staging/build, запускает MCP container, выполняет smoke-tests, переключает production и умеет rollback.

## Требования

- Python `3.11+`
- Git
- Docker
- внешний parser tool, путь к нему задается глобально в `settings.global.json`
  и требуется только если `sources.nativeReportPath` не задан
- MCP image строго один из двух вариантов: `comol/1c_code_metadata_mcp:light` или `comol/1c_code_metadata_mcp:latest`

## Установка

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
```

## Конфигурационная Модель

`project.json` содержит только проектные настройки: `project`, `repo`, `sources`, `mcp`, `paths.root`, `notifications`, `retention`, `rollback`.

Все общие настройки, включая `parser`, `smokeTest`, `toolSmokeTest`, `OPENAI_API_BASE`, `OPENAI_MODEL` и mapping секретов контейнера, лежат в `<data-root>/settings.global.json`.

Блок `sources` поддерживает три сценария:

- main + extension: заданы оба пути;
- extension-only: `mainConfigPath=null`, `mainConfigRequired=false`;
- main-only: `extensionPath=null`, `extensionRequired=false`.

Если готовый `Report.txt` уже формируется внешним штатным процессом, можно передать его updater-у через
`sources.nativeReportPath`. В этом режиме updater копирует указанный файл в `staging/build/metadata/Report.txt`
и не запускает внешний parser tool. Путь задается относительно `<paths.root>/repo`.

Короткий пример `extension-only`:

```json
{
  "project": "esb",
  "sources": {
    "mainConfigPath": null,
    "mainConfigRequired": false,
    "extensionPath": "src/cfe",
    "extensionRequired": true,
    "nativeReportPath": "reports/Report.txt"
  },
  "paths": {
    "root": "C:/mcp-updater-data/esb"
  }
}
```

В `project.json` задается только корень проекта:

```json
{
  "paths": {
    "root": "C:/mcp-updater-data/orders"
  }
}
```

Все рабочие каталоги выводятся строго по соглашению:

```text
C:/mcp-updater-data/
  settings.global.json
  secrets.global.json
  orders/
    project.json
    secrets.local.json
    repo/
    staging/
    chroma/
    state/
    logs/
```

Updater не принимает отдельные `repo.path`, `stagingRoot`, `chromaRoot`, `stateRoot`, `logsRoot`, `secrets.globalFile` или `secrets.projectFile`. `parser` и `smokeTest` в `project.json` также запрещены.

## Global Settings

Глобальные не-секретные настройки лежат в `<data-root>/settings.global.json`, где `<data-root>` это родитель `paths.root`.

Пример: [settings.global.example.json](./settings.global.example.json)

Ключевые блоки:

- `parser` - общий parser tool и его параметры.
- `mcp.env` - глобальные env для MCP container, включая `OPENAI_API_BASE` и `OPENAI_MODEL`.
- `mcp.secretEnv` - mapping env контейнера на имена секретов из secrets files.
- `smokeTest` - общие параметры infrastructure smoke и tool smoke.

`toolSmokeTest.url` запрещен. URL всегда берется из проекта:

- build tool smoke использует `mcp.build.url`;
- production tool smoke использует `mcp.production.url`.

Стандартные контейнерные пути `METADATA_PATH=/app/metadata` и `CODE_PATH=/app/code` добавляются updater-ом автоматически.

Проектные флаги индексации задаются в `project.json` внутри блока `mcp`:

- `indexMetadata` - индексировать metadata;
- `indexCode` - индексировать code;
- `indexHelp` - индексировать help/XSD.

Если help меняется редко и его поиск не нужен в конкретном проекте, help-индексацию можно отключить только для этого проекта:

```json
{
  "mcp": {
    "indexHelp": false
  }
}
```

## Secrets

Секреты не берутся из переменных окружения процесса. Они читаются из JSON-файлов.

Глобальные секреты: `<data-root>/secrets.global.json`

Пример: [secrets.global.example.json](./secrets.global.example.json)

```json
{
  "ONERPA_LICENSE_KEY": "put-license-key-here",
  "OPENROUTER_API_KEY": "put-openrouter-key-here"
}
```

Проектные секреты: `<paths.root>/secrets.local.json`

Пример: [secrets.local.example.json](./secrets.local.example.json)

```json
{
  "GITLAB_TOKEN": "put-project-gitlab-token-here",
  "MCP_UPDATE_WEBHOOK_URL": "put-project-webhook-url-here"
}
```

`secrets.local.json` перекрывает `secrets.global.json`, если ключи совпадают. Рекомендуемая модель: `LICENSE_KEY` и `OPENROUTER_API_KEY` глобальные, `GITLAB_TOKEN` и `MCP_UPDATE_WEBHOOK_URL` проектные.

## GitLab Source Model

Updater работает через обычный Git, не через GitLab API. Локальный репозиторий всегда находится в `<paths.root>/repo`.

Пример блока `repo`:

```json
{
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
  }
}
```

Если `<paths.root>/repo` отсутствует, updater клонирует `repo.cloneUrl`. Если каталог уже существует, updater выполняет `fetch`, `checkout`, `pull --ff-only` и берет target commit из `origin/<branch>`.

## Bootstrap Deployment

Updater поддерживает первый запуск проекта, когда production MCP еще не существует.

В bootstrap-сценарии допустимо, что:

- `<paths.root>/repo` еще отсутствует, и тогда updater сначала делает clone;
- `staging/current`, `chroma/current` и production container еще не существуют;
- в `state` еще нет `current_commit`, `previous_commit` и `last_indexed_commit`.

При первом успешном switch:

- `staging/build` становится `staging/current`;
- `chroma/build` становится `chroma/current`;
- `current_commit` и `last_indexed_commit` записываются в state;
- `previous_commit` остается пустым, пока не появится второй успешный production baseline.

Ограничение bootstrap-сценария: если самый первый production smoke-test после switch падает, automatic rollback не может восстановить предыдущую версию, потому что `previous` baseline еще не существует. В этом случае workflow завершается как `rollback failed`, и требуется ручное вмешательство.

Для самого первого полного build updater теперь не использует общий deadline для build tool smoke. Если `last_indexed_commit` еще отсутствует, bootstrap-run будет бесконечно повторять короткие попытки smoke-check до тех пор, пока MCP tools не начнут отвечать. Ограничение остается только на отдельную попытку через `attemptTimeoutSeconds`.

## Notifications

Webhook хранится в secrets file, а `project.json` содержит только имя секрета:

```json
{
  "notifications": {
    "enabled": true,
    "onSuccess": true,
    "onFailure": true,
    "onRollback": true,
    "webhookUrlSecret": "MCP_UPDATE_WEBHOOK_URL"
  }
}
```

Ошибка notification не маскирует основной статус workflow:

- `update success + notification failed` -> exit code `1`
- `update failed + notification failed` -> сохраняется исходный exit code update
- `rollback success + notification failed` -> exit code `1`
- `rollback failed + notification failed` -> сохраняется исходный exit code rollback

### Telegram Relay

Для Telegram нужен отдельный relay-компонент: updater отправляет универсальный JSON webhook, а relay превращает его в `sendMessage` для Telegram Bot API.

Запуск relay:

```powershell
$env:TELEGRAM_BOT_TOKEN = "<telegram_bot_token>"
$env:TELEGRAM_CHAT_ID = "<telegram_chat_id>"
$env:RELAY_TOKEN = "<shared_secret_token>"
python .\telegram_notification_relay.py
```

Необязательные env:

- `RELAY_HOST` - по умолчанию `127.0.0.1`
- `RELAY_PORT` - по умолчанию `8787`
- `RELAY_PATH` - по умолчанию `/webhook`
- `TELEGRAM_THREAD_ID` - thread/topic id для forum topic
- `TELEGRAM_MESSAGE_PREFIX` - первая строка сообщения, по умолчанию `MCP updater`

Тогда в `<paths.root>/secrets.local.json` можно положить:

```json
{
  "MCP_UPDATE_WEBHOOK_URL": "http://127.0.0.1:8787/webhook?token=<shared_secret_token>"
}
```

Relay принимает payload updater-а, например `project/status/stage/targetCommit/logPath`, и отправляет обычное текстовое сообщение в Telegram.

## Основной Запуск

Команду нужно выполнять из каталога установленного updater-а, то есть из директории, где лежит `update_mcp_project.py`. `project.json` обычно лежит не рядом с updater-ом, а внутри каталога конкретного проекта под data root, поэтому путь в `--config` лучше указывать явно.

Для структуры выше:

```powershell
python .\update_mcp_project.py --config C:\mcp-updater-data\orders\project.json --verbose
```

Если `project.json` действительно лежит рядом с updater-ом, допустим и короткий вариант:

```powershell
python .\update_mcp_project.py --config .\project.json --verbose
```

Поддерживаемые флаги:

- `--config` - путь к `project.json`
- `--force` - переиндексировать даже при совпадении state
- `--no-git-pull` - использовать текущий `HEAD` без `fetch/pull`
- `--rollback` - manual rollback `current <-> previous`
- `--promote-existing-build` - принять уже готовые `staging/build` и `chroma/build`
- `--promote-commit` - commit для записи в state при promote
- `--promote-source-fingerprint` - source fingerprint для записи в state при promote
- `--promote-report-hash` - report hash для записи в state при promote
- `--dry-run` - валидация и расчет плана без parser/docker/switch

## Smoke Tests

Build checks:

- infrastructure smoke использует `mcp.build.url`
- tool smoke использует `mcp.build.url`

Production checks:

- production infrastructure smoke использует `mcp.production.url`
- production MCP tool smoke использует `mcp.production.url`, если `settings.smokeTest.toolSmokeTest.enabled=true`

Production tool smoke-test не должен использовать build URL.

Для MCP endpoint нормально разрешать `405`, потому что `GET /mcp` часто возвращает `405 Method Not Allowed`, хотя streamable HTTP MCP endpoint уже жив.

```json
"acceptableHttpStatusCodes": [200, 400, 404, 405]
```

Для долгой индексации tool smoke использует общий deadline и короткие попытки:

```json
{
  "timeoutSeconds": 54000,
  "attemptTimeoutSeconds": 60,
  "retryIntervalSeconds": 30,
  "diagnostic": false
}
```

Для initial bootstrap это правило отличается: общий `timeoutSeconds` для build tool smoke автоматически отключается, а updater продолжает retry без общего дедлайна. Практически это значит, что для первой полной индексации важны только:

- `attemptTimeoutSeconds` - лимит одной попытки;
- `retryIntervalSeconds` - пауза между попытками.

Для обычного update build теперь переиспользует `chroma/current` как baseline для инкрементальной индексации, если production baseline существует и запуск не идет с `--force`. Это относится и к случаям, когда `Report.txt` изменился: metadata phase все равно выполняется, но code/help получают предыдущий `file_tracker` вместо пустой базы.

Для build container с длинными и шумными логами не стоит полагаться на `logReadyPatterns`: startup-сообщения могут быстро уйти из log tail, и infrastructure smoke упадет, хотя контейнер уже работает нормально. Практически безопасная рекомендация:

```json
{
  "acceptableHttpStatusCodes": [200, 400, 404, 405],
  "logTailLines": 2000,
  "logErrorPatterns": ["Traceback", "Unhandled exception", "CRITICAL"],
  "logReadyPatterns": []
}
```

При `logReadyPatterns: []` readiness определяется по container state, reachable host port, acceptable HTTP status, non-empty Chroma path и отсутствию error patterns в логах.

## Container Runtime

Updater запускает все MCP containers с `--init`, чтобы внутри контейнера корректно reaping-ились дочерние процессы и не накапливались zombie PID.

Production container дополнительно стартует с restart policy:

```text
--restart unless-stopped
```

Это означает, что после перезапуска Docker production baseline должен автоматически подниматься заново, если сам Docker может восстановить контейнер.

Build container остается временным и запускается без restart policy.

## Promote Existing Build

Если initial build упал по timeout, но контейнер продолжил индексироваться и позже стал готов, можно принять уже готовый build:

```powershell
python .\update_mcp_project.py `
  --config .\project.orders.json `
  --promote-existing-build `
  --promote-commit <target_commit_from_log> `
  --promote-source-fingerprint <source_fingerprint_from_log> `
  --promote-report-hash <report_hash_from_log> `
  --verbose
```

Для этого же сценария есть helper-скрипт `promote-existing-build.ps1`. Он может сам взять `Target commit`, `Source fingerprint` и `Report hash` из последнего `*-update.log` проекта или из явно указанного update-лога:

```powershell
powershell -ExecutionPolicy Bypass -File .\promote-existing-build.ps1 `
  -Config C:\mcp-updater-data\upp\project.json `
  -UpdateLog C:\mcp-updater-data\upp\logs\20260520-234903-update.log `
  -UpdaterVerbose
```

Готовая команда для `UPP build -> production`:

```powershell
powershell -ExecutionPolicy Bypass -File .\promote-existing-build.ps1 `
  -Config C:\mcp-updater-data\upp\project.json `
  -UpdateLog C:\mcp-updater-data\upp\logs\20260520-234903-update.log `
  -UpdaterVerbose
```

Готовая команда для `UAT build -> production`:

```powershell
powershell -ExecutionPolicy Bypass -File .\promote-existing-build.ps1 `
  -Config C:\mcp-updater-data\uat\project.json `
  -UpdateLog C:\mcp-updater-data\uat\logs\20260520-234908-update.log `
  -UpdaterVerbose
```

Перед promote стоит проверить build container:

```powershell
python .\mcp_smoke_test.py `
  --url http://localhost:18100/mcp `
  --timeout 300 `
  --index-code `
  --diagnostic `
  --metadata-tool metadatasearch `
  --metadata-query-argument query `
  --metadata-query "Конфигурации" `
  --code-tool codesearch `
  --code-query-argument query `
  --code-query "Процедура"
```

Во время `--promote-existing-build` updater по-прежнему строго требует удалить старый production container, если он существует, но удаление `mcp-...-build` теперь best-effort. Если build container залип, например из-за zombie process внутри старого запуска, promote пишет warning и продолжает production switch.

## Manual Image Upgrade

Если нужно обновить production container на новую версию MCP image без `build`, данные переносить из старого image не нужно. Production baseline хранится не в image, а в примонтированных каталогах:

- `staging/current/metadata -> /app/metadata`
- `staging/current/code -> /app/code`
- `chroma/current -> /app/chroma_db`

Безопасный ручной сценарий:

1. Сначала сохранить текущую конфигурацию container:

```powershell
docker inspect mcp-upp --format "{{.Config.Image}}"
docker inspect mcp-upp --format "{{json .HostConfig.PortBindings}}"
docker inspect mcp-upp --format "{{range .Mounts}}{{println .Source ' -> ' .Destination}}{{end}}"
docker inspect mcp-upp --format "{{range .Config.Env}}{{println .}}{{end}}"
```

2. Сделать backup production baseline:

```powershell
robocopy C:\mcp-updater-data\upp\chroma\current C:\mcp-updater-data\upp\backup\chroma-current /E
robocopy C:\mcp-updater-data\upp\staging\current C:\mcp-updater-data\upp\backup\staging-current /E
```

3. Скачать новый image:

```powershell
docker pull comol/1c_code_metadata_mcp:<new-tag>
```

4. Остановить текущий production container и сохранить его как rollback baseline:

```powershell
docker stop mcp-upp
docker rename mcp-upp mcp-upp-old
```

5. Поднять новый production container на тех же host volumes. Важно:

- не запускать старый и новый container одновременно на одном `chroma/current`;
- оставить `RESET_DATABASE=false`;
- использовать те же ports, mounts и env values, что были у старого container.

Шаблон:

```powershell
docker run -d --init --name mcp-upp --restart unless-stopped `
  -e RESET_DATABASE=false `
  -e RESET_CACHE=false `
  -e USESSE=false `
  -e INDEX_METADATA=true `
  -e INDEX_CODE=true `
  -e INDEX_HELP=false `
  -e OPENAI_API_BASE=<...> `
  -e OPENAI_MODEL=<...> `
  -e OPENAI_API_KEY=<...> `
  -e LICENSE_KEY=<...> `
  -p <HOST_PORT>:8000 `
  -v C:\mcp-updater-data\upp\staging\current\metadata:/app/metadata `
  -v C:\mcp-updater-data\upp\staging\current\code:/app/code `
  -v C:\mcp-updater-data\upp\chroma\current:/app/chroma_db `
  comol/1c_code_metadata_mcp:<new-tag>
```

6. Проверить, что новый container поднялся с правильными флагами:

```powershell
docker logs --tail 200 mcp-upp
docker inspect mcp-upp --format "{{range .Config.Env}}{{println .}}{{end}}" | Select-String "INDEX_HELP|INDEX_CODE|INDEX_METADATA|RESET_DATABASE"
```

7. Если новая версия не подошла, откатить container:

```powershell
docker rm -f mcp-upp
docker rename mcp-upp-old mcp-upp
docker start mcp-upp
```

Рекомендация: даже при ручном upgrade сначала зафиксировать старый image tag из `docker inspect`, чтобы rollback был не только по имени container, но и по версии image.

## Optimization Model

Updater пропускает работу, если:

- `target_commit == last_indexed_commit` и нет `--force`
- source fingerprint совпадает с `last_source_fingerprint`, а production artifacts уже существуют

Если parser уже запущен, дополнительно считается `report hash`:

- если `report hash == last_report_hash`, metadata считается неизменной
- build стартует с копии `chroma/current`
- контейнер получает `RESET_DATABASE=false` и `INDEX_METADATA=false`

Это не полноценный incremental code update. Code phase сейчас отдается MCP image, и фактическую инкрементальность code indexing определяет сам container.

## Rollback

`--rollback`:

- меняет местами `staging/current` и `staging/previous`
- меняет местами `chroma/current` и `chroma/previous`
- поднимает production container на rollback-состоянии
- выполняет production smoke-test по `mcp.production.url`
- обновляет `current_commit` и `previous_commit`
- не переписывает `last_indexed_commit` автоматически

Ручной rollback доступен только после того, как уже существует пара `current`/`previous`.

## Exit Codes

- `0` - success
- `1` - success with warnings
- `2` - config error
- `5` - git pull failed
- `9` - parser failed
- `10` - report validation failed
- `11` - docker unavailable
- `13` - build smoke failed
- `14` - production switch failed
- `15` - production smoke failed
- `16` - rollback failed

Полный список: [mcp_project_updater/constants.py](./mcp_project_updater/constants.py)

## Тесты

```powershell
pytest -q
```

## Файлы

- [project.example.json](./project.example.json)
- [settings.global.example.json](./settings.global.example.json)
- [secrets.global.example.json](./secrets.global.example.json)
- [secrets.local.example.json](./secrets.local.example.json)
- [acceptance-checklist.md](./acceptance-checklist.md)
- [telegram_notification_relay.py](./telegram_notification_relay.py)
