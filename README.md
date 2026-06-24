# MCP Project Updater

`mcp-project-updater` обновляет MCP-индексы 1C-проектов из Git: готовит `Report.txt`, собирает `staging/build`, запускает build MCP container, выполняет smoke-tests, переключает production container и поддерживает rollback.

## Требования

- Python `3.11+`
- Git
- Docker
- Внешний parser tool, если `sources.nativeReportPath` не задан
- CodeMetadata MCP image только из stable allow-list:
  - `comol/1c_code_metadata_mcp:light`
  - `comol/1c_code_metadata_mcp:latest`

Beta/arm64 tags в production updater не поддерживаются.

## Установка

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
```

## Конфигурация

`project.json` содержит только проектные настройки: `project`, `repo`, `sources`, `mcp`, `notifications`, `retention`, `rollback`.

Общие настройки (`parser`, `projectDefaults`, `smokeTest`, универсальный `mcp.secretEnv`) лежат в `<data-root>/settings.global.json`. Проектные `mcp.env` и `mcp.secretEnv` используются для OpenAI/OpenRouter параметров конкретного проекта. Секреты читаются из `<data-root>/secrets.global.json` и `<paths.root>/secrets.local.json`; проектные secrets перекрывают global secrets с тем же именем.

Типовой compact project config хранит только уникальные значения:

```json
{
  "project": "orders",
  "mcp": {
    "image": "comol/1c_code_metadata_mcp:latest",
    "hostPort": 8100
  }
}
```

Если `paths.root` не задан, он равен директории `project.json`. Для `C:\mcp-updater-data\orders\project.json` это `C:\mcp-updater-data\orders`, а global settings читаются из `C:\mcp-updater-data\settings.global.json`.

`settings.global.json` может задавать common defaults:

```json
{
  "projectDefaults": {
    "indexStorageRootTemplate": "\\\\wsl.localhost\\Ubuntu\\home\\norkins\\mcp-indexes\\{project}",
    "productionContainerNameTemplate": "mcp-{project}",
    "buildContainerNameTemplate": "mcp-{project}-build",
    "urlScheme": "http",
    "urlHost": "localhost",
    "urlPath": "/mcp",
    "buildHostPortOffset": 10000,
    "containerPort": 8000
  }
}
```

Для `project=orders` и `mcp.hostPort=8100` updater выводит:

- production container: `mcp-orders`
- build container: `mcp-orders-build`
- production URL: `http://localhost:8100/mcp`
- build port/URL: `18100`, `http://localhost:18100/mcp`
- index storage root из `indexStorageRootTemplate`

Все derived values можно задать явно как override: `paths.root`, `mcp.indexStorageRoot`, `mcp.containerPort`, `mcp.production.*`, `mcp.build.*`, `mcp.indexContainerPath`.

`mcp.indexStorageRoot` является единственным root для `build/current/previous/failed` index storage. Updater больше не использует `<paths.root>/chroma` как default.

`mcp.indexContainerPath` задает путь тома внутри контейнера. Для CodeMetadata MCP default равен `/app/chroma_db`, поэтому поле можно не задавать. Не переключайте CodeMetadata на `/app/zvec_db`: профильная инструкция MCP_Distr6 и разработчик подтверждают, что CodeMetadata сохраняет `/app/chroma_db` как внешний Docker-контракт.

Правила path validation:

- Windows: `mcp.indexStorageRoot` должен быть WSL UNC path `\\wsl.localhost\<Distro>\...` или `\\wsl$\<Distro>\...`.
- Linux: `mcp.indexStorageRoot` должен быть absolute native path.
- Updater проверяет доступность storage path или его parent до Git/parser/Docker операций.
- `mcp.indexContainerPath`, если задан, должен быть absolute Unix-style path внутри контейнера, например `/app/chroma_db`.

Запрещено задавать в `project.json`: `repo.path`, `stagingRoot`, `chromaRoot`, `stateRoot`, `logsRoot`, `secrets.globalFile`, `secrets.projectFile`, `parser`, `smokeTest`, `toolSmokeTest`.

Перед реальным запуском compact config проверяйте через `--dry-run`: updater печатает resolved `paths.root`, `mcp.indexStorageRoot`, container names, host ports и URLs.

`OPENAI_API_BASE`, `OPENAI_MODEL` и `OPENAI_API_KEY` задаются на уровне проекта только если конкретному MCP runtime нужен внешний embedding API:

```json
{
  "mcp": {
    "env": {
      "OPENAI_API_BASE": "https://openrouter.ai/api/v1",
      "OPENAI_MODEL": "qwen/qwen3-embedding-8b"
    },
    "secretEnv": {
      "OPENAI_API_KEY": "OPENROUTER_API_KEY"
    }
  }
}
```

Secret `OPENROUTER_API_KEY` в этом случае можно положить в `<paths.root>/secrets.local.json`. Если проект не задает эти поля, updater не требует `OPENROUTER_API_KEY` и не передает `OPENAI_API_BASE`, `OPENAI_MODEL`, `OPENAI_API_KEY` в контейнер.

## Runtime Layout

Для проекта `orders`:

```text
C:/mcp-updater-data/
  settings.global.json
  secrets.global.json
  orders/
    project.json
    secrets.local.json
    repo/
    staging/
    state/
    logs/

\\wsl.localhost\Ubuntu\mcp-indexes\orders\
  build/
  current/
  previous/
  failed-<timestamp>/
```

Host-side storage root переехал в WSL, а container mount target задается через `mcp.indexContainerPath`. Для CodeMetadata MCP используется `/app/chroma_db` по умолчанию.

## Smoke Settings

В `settings.global.json` используйте backend-neutral имя:

```json
{
  "smokeTest": {
    "infrastructure": {
      "requireIndexStorageNotEmpty": true
    }
  }
}
```

Legacy `requireChromaNotEmpty` читается только как compatibility alias. Если не задано ни новое, ни legacy имя, config validation падает по `settings.smokeTest.infrastructure.requireIndexStorageNotEmpty`.

Для MCP endpoint обычно допустимы `200`, `400`, `404`, `405`, `406`:

```json
"acceptableHttpStatusCodes": [200, 400, 404, 405, 406]
```

При `logReadyPatterns: []` readiness определяется по container state, reachable host port, acceptable HTTP status, non-empty MCP index storage path и отсутствию error patterns в логах.

## Основной Запуск

```powershell
python .\update_mcp_project.py --config C:\mcp-updater-data\orders\project.json --verbose
```

Поддерживаемые флаги:

- `--config` - путь к `project.json`
- `--force` - rebuild текущего configured `mcp.indexStorageRoot` без seed/reuse из `current`
- `--storage-migration` - явный ChromaDB -> zvec cutover без seed из старого/current storage
- `--no-git-pull` - использовать текущий `HEAD` без `fetch/pull`
- `--rollback` - manual rollback `current <-> previous`
- `--promote-existing-build` - принять уже готовые `staging/build` и `index storage/build`
- `--promote-commit` - commit для записи в state при promote
- `--promote-source-fingerprint` - source fingerprint для записи в state при promote
- `--promote-report-hash` - report hash для записи в state при promote
- `--dry-run` - validation и расчет плана без parser/docker/switch

`--storage-migration` нельзя комбинировать с `--force`, `--rollback` или `--promote-existing-build`.

PowerShell wrapper:

```powershell
powershell -ExecutionPolicy Bypass -File .\update-mcp-project.ps1 `
  -Config C:\mcp-updater-data\orders\project.json `
  -StorageMigration `
  -Verbose
```

## Windows Task Scheduler

Для регулярного запуска используйте PowerShell wrapper `update-mcp-project.ps1`.

Action:

- Program/script:

```text
powershell.exe
```

- Arguments:

```text
-NoProfile -ExecutionPolicy Bypass -File "C:\Work\MCP updater\mcp-project-updater\update-mcp-project.ps1" -Config "C:\mcp-updater-data\orders\project.json" -Verbose
```

- Start in:

```text
C:\Work\MCP updater\mcp-project-updater
```

Для другого проекта меняйте только `-Config`, например:

```text
-Config "C:\mcp-updater-data\monitoring\project.json"
```

Пример через `schtasks`:

```powershell
schtasks /Create /TN "MCP Updater Orders" /SC DAILY /ST 03:00 /RL HIGHEST /F /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -File \"C:\Work\MCP updater\mcp-project-updater\update-mcp-project.ps1\" -Config \"C:\mcp-updater-data\orders\project.json\" -Verbose"
```

Важные настройки Task Scheduler:

- `Run only when user is logged on` - используйте, если Docker Desktop запущен как пользовательское приложение.
- `Run with highest privileges` - рекомендуется включить.
- User задачи должен иметь доступ к Git, Docker Desktop, WSL UNC path и secrets files.
- В `Conditions` снимите `Start the task only if the computer is on AC power`, если это сервер или рабочая машина, где запуск не должен зависеть от питания.
- В `Settings` задайте `Stop the task if it runs longer than`, например 12-24 часа для больших конфигураций.

Scheduled run выполняет полный update workflow: Git prepare, build, smoke-tests, production switch и production smoke-test. Отдельного режима "только подготовить build без switch" сейчас нет.

## zvec Migration

Новый CodeMetadata MCP использует zvec внутри контейнера. Updater не конвертирует старую ChromaDB database и не seed-ит zvec build из старого `<paths.root>/chroma/current`.

Перед migration:

1. Добавить `settings.projectDefaults.indexStorageRootTemplate` или явный `mcp.indexStorageRoot` в проект.
2. Оставить `mcp.indexContainerPath` отсутствующим или явно задать `/app/chroma_db` для CodeMetadata.
3. На Windows указать WSL-mounted root.
4. Сделать backup старого deployment: container metadata, state, `staging/current`, старый `<paths.root>/chroma/current`.
5. Вручную обновить stable image:

```powershell
docker pull comol/1c_code_metadata_mcp:light
```

6. Запустить updater с `--storage-migration`.

`docker pull` намеренно не выполняется updater-ом автоматически.

Migration workflow:

- build storage создается с нуля на `mcp.indexStorageRoot/build`;
- build smoke-tests выполняются до удаления старого production container;
- после успешных build smoke-tests старый production container удаляется;
- `build` переключается в `current`;
- запускается новый zvec-backed production container;
- production smoke-test выполняется только после запуска нового production container;
- state обновляется только после успешного production smoke-test.

Если production smoke-test падает в `--storage-migration`, updater сохраняет production logs, останавливает неисправный новый production container, не запускает automatic rollback и возвращает ошибку с manual recovery guidance. Восстановление выполняется вручную из backup старого deployment.

## Обычный Incremental Update и `--force`

Обычный update без `--storage-migration` и без `--force` может seed-ить `mcp.indexStorageRoot/build` из `mcp.indexStorageRoot/current`, если текущий baseline существует. Это ускоряет повторные zvec updates.

`--force` отключает seed/reuse только для текущего configured storage root. Он не является marker-ом ChromaDB -> zvec migration.

## Promote Existing Build

Если build container долго индексировался и стал готов позже failed update, можно принять готовый build:

```powershell
python .\update_mcp_project.py `
  --config .\project.orders.json `
  --promote-existing-build `
  --promote-commit <target_commit_from_log> `
  --promote-source-fingerprint <source_fingerprint_from_log> `
  --promote-report-hash <report_hash_from_log> `
  --verbose
```

Helper:

```powershell
powershell -ExecutionPolicy Bypass -File .\promote-existing-build.ps1 `
  -Config C:\mcp-updater-data\orders\project.json `
  -UpdaterVerbose
```

Если `-UpdateLog` не указан, helper читает `paths.root` из project config и берет самый поздний по timestamp в имени `YYYYMMDD-HHMMSS-update.log` из `<paths.root>\logs`.

Явный log можно указать как override:

```powershell
powershell -ExecutionPolicy Bypass -File .\promote-existing-build.ps1 `
  -Config C:\mcp-updater-data\orders\project.json `
  -UpdateLog C:\mcp-updater-data\orders\logs\20260520-234903-update.log `
  -UpdaterVerbose
```

Promote проверяет build infrastructure/tool smoke до production switch.

## Rollback

`--rollback`:

- меняет местами `staging/current` и `staging/previous`;
- меняет местами `mcp.indexStorageRoot/current` и `mcp.indexStorageRoot/previous`;
- поднимает production container на rollback-состоянии;
- выполняет production smoke-test по `mcp.production.url`;
- обновляет `current_commit` и `previous_commit`;
- не переписывает `last_indexed_commit`.

Automatic rollback используется для обычного production smoke failure, если compatible `previous` baseline существует. Для `--storage-migration` automatic rollback отключен.

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

## Тесты

```powershell
pytest -q
openspec validate support-zvec-codemetadata --json
```
