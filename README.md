# MCP Project Updater

`mcp-project-updater` обновляет MCP-индексы 1C-проектов из Git: собирает `Report.txt`, готовит staging/build, запускает MCP container, выполняет smoke-tests, переключает production и умеет rollback.

## Требования

- Python `3.11+`
- Git
- Docker
- внешний parser tool, путь к нему задается глобально в `settings.global.json`
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
