# MCP Project Updater Acceptance Checklist

Checklist для первого реального запуска на parser, Docker и stable CodeMetadata MCP image.

## 1. Preflight

- Проверить, что Python `3.11+`, `git` и `docker` доступны в `PATH`.
- Проверить, что stable image уже обновлен вручную: `docker pull comol/1c_code_metadata_mcp:light` или `docker pull comol/1c_code_metadata_mcp:latest`.
- Проверить, что `project.json` задает `mcp.image` только как `comol/1c_code_metadata_mcp:light` или `comol/1c_code_metadata_mcp:latest`.
- Проверить, что beta/arm64 tags не используются.
- Проверить, что `paths.root` задан, например `C:/mcp-updater-data/orders`.
- Проверить, что `mcp.indexStorageRoot` задан.
- Для CodeMetadata оставить `mcp.indexContainerPath` отсутствующим или явно задать `/app/chroma_db`.
- Не задавать `/app/zvec_db` для CodeMetadata без подтвержденного Docker-контракта конкретного образа.
- На Windows проверить, что `mcp.indexStorageRoot` указывает на WSL UNC path: `\\wsl.localhost\<Distro>\...` или `\\wsl$\<Distro>\...`.
- На Linux проверить, что `mcp.indexStorageRoot` является absolute native path.
- Проверить, что `mcp.indexStorageRoot` или его parent доступны с host-side updater process.
- Проверить, что `<paths.root>/repo` существует как Git repo или задан корректный `repo.cloneUrl`.
- Проверить, что `<paths.root>/staging`, `<paths.root>/state`, `<paths.root>/logs` доступны на запись или могут быть созданы.
- Проверить, что `<paths.root.parent>/settings.global.json` содержит `parser`, `mcp`, `smokeTest`, `smokeTest.toolSmokeTest`.
- Проверить, что `settings.parser.toolPath` и `settings.smokeTest.toolSmokeTest.toolPath` указывают на существующие файлы.
- Проверить, что `settings.smokeTest.infrastructure.requireIndexStorageNotEmpty` задан.
- Проверить, что `settings.smokeTest.toolSmokeTest` не содержит `url`.
- Проверить, что `<paths.root.parent>/secrets.global.json` содержит универсальные secrets, включая `ONERPA_LICENSE_KEY`.
- Если проект задает `mcp.secretEnv.OPENAI_API_KEY`, проверить, что `<paths.root>/secrets.local.json` или global secrets содержит указанный secret, например `OPENROUTER_API_KEY`.
- Если проект не задает `mcp.secretEnv.OPENAI_API_KEY`, убедиться, что `OPENROUTER_API_KEY` не обязателен для config validation.
- Проверить, что `mcp.production.containerName` и `mcp.build.containerName` различаются.
- Проверить, что `mcp.production.hostPort` и `mcp.build.hostPort` не конфликтуют.

## 2. Config Sanity

- Создать рабочий `project.json` на основе [project.example.json](./project.example.json).
- Убедиться, что `project.json` не содержит `repo.path`, `stagingRoot`, `chromaRoot`, `stateRoot`, `logsRoot`, `globalFile`, `projectFile`, `parser`, `smokeTest`, `toolSmokeTest`.
- Если проект использует внешний embedding API, проверить, что `mcp.env.OPENAI_API_BASE` и `mcp.env.OPENAI_MODEL` заданы в `project.json`, а не в global settings.
- Убедиться, что build URL задан только в `mcp.build.url`.
- Убедиться, что production URL задан только в `mcp.production.url`.
- Убедиться, что `mcp.indexContainerPath`, если задан, является absolute Unix-style container path.
- Проверить `settings.smokeTest.infrastructure.acceptableHttpStatusCodes`; для MCP endpoint обычно нужен `405`.
- Для шумных build containers предпочтительно задать `logTailLines >= 2000`, а `logReadyPatterns` оставить пустым списком.

## 3. Dry Run

```powershell
python .\update_mcp_project.py --config .\project.json --dry-run --verbose
```

Проверить:

- команда завершилась с `exit code 0`;
- config загрузился без validation errors;
- в логах виден derived repo path `<paths.root>/repo`;
- в логах виден `MCP index storage root`;
- корректно определены `target_commit`, `last_indexed_commit`, `current_commit`, `previous_commit`;
- source detection нашел ожидаемые `src/cf` и, при наличии, `src/cfe`.

## 4. zvec Storage Migration

Использовать для перевода старых CodeMetadata installations с ChromaDB-backed storage на zvec-backed runtime.

Подготовка:

- Сделать backup старого deployment: container inspect, image tag, state files, `<paths.root>/staging/current`, старый `<paths.root>/chroma/current`.
- Не использовать generic MCP_Distr6 option "использовать те же базы" для ChromaDB -> zvec migration.
- Убедиться, что новый `mcp.indexStorageRoot` пустой или подготовлен как target storage root.

Запуск:

```powershell
python .\update_mcp_project.py --config .\project.json --storage-migration --verbose
```

Проверить:

- build storage создан в `mcp.indexStorageRoot/build`;
- build storage не seed-ился из старого `<paths.root>/chroma/current`;
- build infrastructure smoke-test прошел по `mcp.build.url`;
- build MCP tool smoke-test прошел по `mcp.build.url`;
- старый production container удален только после успешных build smoke-tests;
- `mcp.indexStorageRoot/build` стал `mcp.indexStorageRoot/current`;
- production container стартовал на stable CodeMetadata image;
- production smoke-test прошел по `mcp.production.url`;
- state обновился только после успешного production smoke-test.

Если production smoke-test падает в `--storage-migration`:

- проверить, что production logs сохранены;
- проверить, что неисправный новый production container остановлен;
- automatic rollback не должен запускаться;
- recovery выполняется вручную из backup старого deployment.

## 5. First Normal Update

```powershell
python .\update_mcp_project.py --config .\project.json --verbose
```

Проверить:

- создан `<paths.root>/staging/build`;
- создан `parser-config.json`;
- parser завершился допустимым exit code;
- появился `Report.txt`;
- report validation прошла успешно;
- build container поднялся;
- build smoke-tests прошли до production switch;
- production smoke-test прошел после запуска нового production container;
- появились `<paths.root>/staging/current` и `mcp.indexStorageRoot/current`;
- `state/current_commit` и `state/last_indexed_commit` обновлены.

## 6. No-Change Scenario

```powershell
python .\update_mcp_project.py --config .\project.json
```

Проверить:

- updater корректно определяет `no changes`;
- повторные parser/docker/switch не запускаются;
- команда завершается успешно.

## 7. Force Scenario

```powershell
python .\update_mcp_project.py --config .\project.json --force
```

Проверить:

- rebuild запускается даже при совпадающем `last_indexed_commit`;
- build не seed-ится из `mcp.indexStorageRoot/current`;
- `--force` не трактуется как ChromaDB -> zvec migration marker.

## 8. Rollback Scenario

Подготовка:

- убедиться, что существуют `<paths.root>/staging/current` и `<paths.root>/staging/previous`;
- убедиться, что существуют `mcp.indexStorageRoot/current` и `mcp.indexStorageRoot/previous`;
- убедиться, что в state есть `current_commit` и `previous_commit`.

Запуск:

```powershell
python .\update_mcp_project.py --config .\project.json --rollback --verbose
```

Проверить:

- `current` и `previous` поменялись местами в staging и index storage;
- production container стартовал на rollback-состоянии;
- production smoke-test прошел по `mcp.production.url`;
- `state/current_commit` и `state/previous_commit` поменялись местами;
- `state/last_indexed_commit` не изменился автоматически.

## 9. Promote Existing Build Scenario

Использовать, если updater завершился по `settings.smokeTest.toolSmokeTest.timeoutSeconds`, но build container продолжил long-running indexing и позже стал готов.

Подготовка:

- убедиться, что `<paths.root>/staging/build` существует;
- убедиться, что `mcp.indexStorageRoot/build` существует;
- убедиться, что build container доступен по `mcp.build.url`;
- взять из failed update log `Target commit`, `Source fingerprint` и `Report hash`.

Запуск:

```powershell
python .\update_mcp_project.py `
  --config .\project.json `
  --promote-existing-build `
  --promote-commit <target_commit_from_log> `
  --promote-source-fingerprint <source_fingerprint_from_log> `
  --promote-report-hash <report_hash_from_log> `
  --verbose
```

Проверить:

- build infrastructure smoke-test прошел по `mcp.build.url`;
- build MCP tool smoke-test прошел по `mcp.build.url`;
- `staging/build` стал `staging/current`;
- `mcp.indexStorageRoot/build` стал `mcp.indexStorageRoot/current`;
- production smoke-test прошел по `mcp.production.url`;
- state fingerprints и hashes записаны.

## 10. Failure and Automatic Rollback Drill

Проводить только после того, как существует compatible `previous` baseline. Для `--storage-migration` automatic rollback отключен и этот drill неприменим.

Для controlled drill искусственно сломать production smoke-test:

- указать невалидный `mcp.production.url`; или
- временно сломать production readiness condition.

Проверить:

- production smoke-test падает;
- для обычного update запускается automatic rollback;
- production возвращается на предыдущий рабочий индекс;
- `last_indexed_commit` не обновляется на неуспешный commit;
- при `rollback.preserveFailedIndex=true` сохраняется `failed-<timestamp>`;
- failure/rollback notification отправляется, если включена.

## 11. Exit Codes

- `0` - успешный update;
- `1` - update или rollback успешен, но notification не отправилась;
- `2` - сломан config или settings;
- `11` - Docker недоступен;
- `15` - production smoke-test failed;
- `16` - rollback failed.

## 12. Sign-Off

Готово к боевому использованию, если:

- dry-run проходит стабильно;
- storage migration прошла для старых installations;
- минимум один обычный update проходит успешно;
- manual rollback проходит успешно;
- automatic rollback drill подтвержден для non-migration сценария;
- logs и notifications соответствуют ожиданиям;
- state files корректно отражают текущее production-состояние.
