# PRD: MCP Project Updater

## 1. Назначение

MCP Project Updater автоматизирует обновление CodeMetadata MCP для 1C-проектов:

- берет target commit из Git;
- формирует или принимает готовый `Report.txt`;
- готовит `staging/build`;
- запускает build MCP container;
- выполняет build smoke-tests;
- переключает production container;
- выполняет production smoke-test;
- обновляет state только после успешного production smoke-test;
- поддерживает manual rollback и automatic rollback для обычных non-migration failures.

## 2. Текущий CodeMetadata Runtime

CodeMetadata MCP перешел на zvec внутри контейнера. Внешний container interface не изменился:

- один контейнер;
- port `8000`;
- endpoint `http://localhost:8000/mcp`;
- metadata mount `/app/metadata`;
- code mount `/app/code`;
- index storage mount `/app/chroma_db` по умолчанию.

Updater не анализирует внутренний формат zvec и не конвертирует старую ChromaDB database.

Container mount target для index storage задается проектным `mcp.indexContainerPath`. Для CodeMetadata default равен `/app/chroma_db`; путь `/app/zvec_db` не выбирается автоматически по факту использования zvec и может применяться только как явный override для MCP-образа с таким Docker-контрактом.

## 3. Stable Images

Production allow-list фиксируется только на stable tags:

- `comol/1c_code_metadata_mcp:light`
- `comol/1c_code_metadata_mcp:latest`

Beta/arm64 tags не поддерживаются.

Updater не выполняет `docker pull` автоматически. Перед storage migration оператор вручную выполняет:

```powershell
docker pull comol/1c_code_metadata_mcp:<tag>
```

## 4. Конфигурационная Модель

`project.json` содержит только project-level настройки:

- `project`
- `repo`
- `sources`
- `mcp`
- `paths.root` как optional override
- `notifications`
- `retention`
- `rollback`

`settings.global.json` содержит общие настройки:

- `parser`
- `projectDefaults`
- `mcp.secretEnv` только для универсальных secrets, например `LICENSE_KEY`
- `smokeTest`

`project.json` может содержать `mcp.env` и `mcp.secretEnv` для опциональных проектных OpenAI/OpenRouter параметров. `OPENAI_API_BASE`, `OPENAI_MODEL` и `OPENAI_API_KEY` задаются только так, если конкретному проекту нужен внешний embedding API:

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

Если эти поля не заданы, updater не требует `OPENROUTER_API_KEY` и не передает `OPENAI_API_BASE`, `OPENAI_MODEL`, `OPENAI_API_KEY` в контейнер.

`project.json` не должен содержать `parser`, `smokeTest`, `toolSmokeTest`, `repo.path`, `paths.stagingRoot`, `paths.chromaRoot`, `paths.stateRoot`, `paths.logsRoot`, `secrets.globalFile`, `secrets.projectFile`.

Derived paths:

- Если `paths.root` не задан, он равен директории `project.json`.
- Git checkout: `<paths.root>/repo`
- Staging: `<paths.root>/staging`
- State: `<paths.root>/state`
- Logs: `<paths.root>/logs`
- Secrets: `<paths.root>/secrets.local.json`
- Global settings/secrets: `<paths.root.parent>/settings.global.json`, `<paths.root.parent>/secrets.global.json`

Index storage больше не выводится из `paths.root`, но может выводиться из `settings.global.json` `projectDefaults.indexStorageRootTemplate`.

## 5. MCP Index Storage

Project config может задать `mcp.indexStorageRoot` явно или использовать `settings.global.json` `projectDefaults.indexStorageRootTemplate`:

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

`mcp.hostPort` задает compact production host port. Если `mcp.build.hostPort` не задан, build port выводится как production port + `projectDefaults.buildHostPortOffset`. Если URLs не заданы явно, они выводятся из scheme/host/path и resolved ports. Если container names не заданы явно, они выводятся из templates.

Common MCP flags по умолчанию:

- `indexCode=true`
- `indexMetadata=true`
- `indexHelp=false`
- `resetDatabaseOnBuild=true`
- `resetCache=false`
- `useSse=false`
- `useGpu=false`

`mcp.indexStorageRoot` является единственным root для:

- `build`
- `current`
- `previous`
- `failed-<timestamp>`

Validation:

- Windows: разрешены только `\\wsl.localhost\<Distro>\...` и `\\wsl$\<Distro>\...`.
- Linux: требуется absolute native path.
- До Git/parser/Docker updater проверяет доступность storage path или его parent.

Legacy runtime alias `paths.chroma_root` может существовать только как read-only compatibility alias на `paths.index_storage_root`. Он не должен указывать на `<paths.root>/chroma`.

`mcp.indexContainerPath`:

- опционален;
- default для CodeMetadata: `/app/chroma_db`;
- должен быть absolute Unix-style path внутри контейнера;
- используется как target path в build и production Docker volume mounts.

## 6. Smoke Settings

Новое имя настройки:

```json
{
  "smokeTest": {
    "infrastructure": {
      "requireIndexStorageNotEmpty": true
    }
  }
}
```

`requireChromaNotEmpty` читается только как compatibility alias. Если не задано ни новое, ни legacy имя, validation error должен ссылаться на `settings.smokeTest.infrastructure.requireIndexStorageNotEmpty`.

Диагностика должна использовать backend-neutral текст `MCP index storage path`.

Tool smoke-test должен доказывать использование готового vector index. Для включенного `mcp.indexMetadata` успешный `metadatasearch` должен возвращать `search_layer=vector+bm25`, а `stats.collections.metadata` должен быть больше `0`. Для включенного `mcp.indexCode` успешный `codesearch` должен возвращать `search_layer=vector+bm25`, а `stats.collections.code` должен быть больше `0`. Fallback layers вроде `grep` или `live_xml` не считаются успешной проверкой готового vector index.

## 7. CLI

Поддерживаемые режимы:

- обычный update;
- `--force`;
- `--storage-migration`;
- `--repair-metadata-index`;
- `--rollback`;
- `--promote-existing-build`;
- `--dry-run`.

`--storage-migration` несовместим с:

- `--force`
- `--rollback`
- `--promote-existing-build`

`--repair-metadata-index` несовместим с:

- `--force`
- `--storage-migration`
- `--rollback`
- `--promote-existing-build`
- `--dry-run`

`--force` остается rebuild control для текущего configured storage root и не является marker-ом ChromaDB -> zvec migration.

## 8. Обычный Update Workflow

1. Загрузить config и settings.
2. Проверить lock.
3. Подготовить Git repo и target commit.
4. Определить источники.
5. Рассчитать source fingerprint.
6. Если commit/fingerprint/report/storage не изменились и нет `--force` / `--repair-metadata-index`, пропустить update.
7. Подготовить `staging/build`.
8. Сформировать или скопировать `Report.txt`.
9. Выполнить report validation.
10. Рассчитать report hash.
11. Если запуск не `--force`, не `--storage-migration` и `mcp.indexStorageRoot/current` существует, build может seed-иться из current storage.
12. Запустить build container.
13. Выполнить build infrastructure smoke-test.
14. Выполнить build tool smoke-test, если включен.
15. Сохранить build container logs.
16. Перейти к production switch.

### Metadata Repair Workflow

`--repair-metadata-index` используется, когда `current` storage содержит живой code/forms index, но metadata vector collection пустая или `metadatasearch` обслуживается fallback layer.

Требования:

- updater не применяет early skip по unchanged commit/report;
- `mcp.indexStorageRoot/current` должен существовать до запуска build;
- `mcp.indexStorageRoot/build` seed-ится из `current`;
- build container стартует с `RESET_DATABASE=false`, `INDEX_METADATA=true`, `INDEX_CODE=false`, `INDEX_HELP=false`;
- updater вызывает MCP tool `reindex(force=true)` только на build container;
- поскольку code phase выключена в build env, `force=true` пересобирает metadata phase и не пересобирает code index;
- build smoke должен подтвердить `stats.collections.metadata > 0` и, если `mcp.indexCode=true`, `stats.collections.code > 0`;
- production switch выполняется только после успешных build checks.

`--repair-metadata-index` не должен вызывать `reindex` на production container.

## 9. Production Switch

Production switch допускается только после успешных build smoke-tests.

Порядок:

1. Проверить наличие `staging/build` и `mcp.indexStorageRoot/build`.
2. Удалить старый production container.
3. Best-effort удалить build container.
4. Удалить старые `previous` artifacts.
5. Переместить `staging/current` в `staging/previous`, если существует.
6. Переместить `mcp.indexStorageRoot/current` в `mcp.indexStorageRoot/previous`, если существует.
7. Переместить `staging/build` в `staging/current`.
8. Переместить `mcp.indexStorageRoot/build` в `mcp.indexStorageRoot/current`.
9. Запустить новый production container с `RESET_DATABASE=false` и `INDEX_METADATA=false`, `INDEX_CODE=false`, `INDEX_HELP=false`.
10. Выполнить production smoke-test.
11. Только после успешного production smoke-test записать `current_commit`, `previous_commit`, `last_indexed_commit`, `last_source_fingerprint`, `last_report_hash`.

Production smoke-test физически выполняется только после switch и запуска нового production container.
Production container не выполняет indexing; он обслуживает готовый `mcp.indexStorageRoot/current`, подготовленный build-контейнером. Updater запускает production с `INDEX_METADATA=false`, `INDEX_CODE=false`, `INDEX_HELP=false` и `REINDEX_INTERVAL_SEC=0`.

## 10. Storage Migration Workflow

Storage migration используется для ChromaDB -> zvec cutover:

```powershell
python .\update_mcp_project.py --config .\project.json --storage-migration --verbose
```

Требования:

- build storage создается с нуля на `mcp.indexStorageRoot/build`;
- updater не seed-ит build из `mcp.indexStorageRoot/current`;
- updater не читает старый `<paths.root>/chroma/current`;
- старую ChromaDB database можно использовать только как backup/manual recovery source;
- generic MCP_Distr6 option "использовать те же базы" запрещен для ChromaDB -> zvec migration.

Если failure происходит до production switch, старый production container остается рабочим.

Если production smoke-test падает после migration switch:

- updater сохраняет production logs;
- updater останавливает неисправный новый production container;
- automatic rollback не запускается;
- workflow возвращает ошибку с manual recovery guidance;
- оператор восстанавливается вручную из backup старого deployment.

## 11. Rollback

Manual rollback:

- меняет местами `staging/current` и `staging/previous`;
- меняет местами `mcp.indexStorageRoot/current` и `mcp.indexStorageRoot/previous`;
- запускает production container на rollback state без `INDEX_*` и с `REINDEX_INTERVAL_SEC=0`;
- выполняет production smoke-test;
- меняет местами `current_commit` и `previous_commit`;
- не меняет `last_indexed_commit`.

Automatic rollback применяется только для обычного non-migration production smoke failure, когда compatible `previous` baseline существует.

## 12. Promote Existing Build

`--promote-existing-build` принимает уже готовые:

- `<paths.root>/staging/build`
- `mcp.indexStorageRoot/build`

Promote выполняет build smoke-tests до production switch и затем обычный production switch.

PowerShell helper `promote-existing-build.ps1` принимает `-UpdateLog` как optional override. Если `-UpdateLog` не указан, helper читает `paths.root` из project config и выбирает самый поздний по timestamp в имени `YYYYMMDD-HHMMSS-update.log` из `<paths.root>/logs`, чтобы извлечь `Target commit`, `Source fingerprint` и `Report hash`.

## 13. Exit Codes

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

## 14. Acceptance

Готово, если:

- config требует explicit `mcp.indexStorageRoot` или `settings.projectDefaults.indexStorageRootTemplate`;
- config поддерживает `mcp.indexContainerPath` с default `/app/chroma_db`;
- Windows validation запрещает обычные Windows paths для index storage;
- Linux validation принимает absolute native path;
- storage migration не seed-ит zvec build из старой ChromaDB database;
- build smoke-tests gate-ят production switch;
- production smoke-test выполняется после запуска нового production container;
- state обновляется только после successful production smoke-test;
- storage migration production smoke failure не вызывает automatic rollback;
- docs/examples не предлагают beta/arm64 images и не советуют reuse старой ChromaDB database для zvec migration.
