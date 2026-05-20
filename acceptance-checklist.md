# MCP Project Updater Acceptance Checklist

Checklist для первого реального запуска на настоящем parser, Docker и MCP image.

## 1. Preflight

- Проверить, что Python `3.11+`, `git` и `docker` доступны в `PATH`.
- Проверить, что `<paths.root.parent>/settings.global.json` существует.
- Проверить, что `settings.global.json` содержит блоки `parser`, `mcp`, `smokeTest`, `smokeTest.toolSmokeTest`.
- Проверить, что `settings.parser.toolPath` указывает на существующий parser tool.
- Проверить, что `settings.smokeTest.toolSmokeTest.toolPath` указывает на существующий `mcp_smoke_test.py`.
- Проверить, что `settings.smokeTest.toolSmokeTest` не содержит `url`.
- Проверить, что `mcp.image` равен `comol/1c_code_metadata_mcp:light` или `comol/1c_code_metadata_mcp:latest`.
- Проверить, что задан `paths.root`, например `C:/mcp-updater-data/orders`.
- Проверить, что `<paths.root>/repo` существует как Git repo или задан корректный `repo.cloneUrl`.
- Проверить, что `<paths.root>/staging`, `<paths.root>/chroma`, `<paths.root>/state`, `<paths.root>/logs` доступны на запись или могут быть созданы.
- Проверить, что `<paths.root.parent>/secrets.global.json` содержит глобальные секреты `ONERPA_LICENSE_KEY` и `OPENROUTER_API_KEY`, если они используются.
- Проверить, что `<paths.root>/secrets.local.json` содержит проектные секреты `GITLAB_TOKEN` и `MCP_UPDATE_WEBHOOK_URL`, если они используются.
- Проверить, что `repo.auth.tokenSecret` указывает на ключ из secrets files, а не на env-переменную процесса.
- Проверить, что `notifications.webhookUrlSecret` указывает на ключ из secrets files, а не на env-переменную процесса.
- Проверить, что `mcp.production.containerName` и `mcp.build.containerName` различаются.
- Проверить, что `mcp.production.hostPort` и `mcp.build.hostPort` не конфликтуют.

## 2. Config Sanity

- Создать рабочий `project.json` на основе [project.example.json](./project.example.json).
- Убедиться, что `project.json` не содержит `repo.path`, `stagingRoot`, `chromaRoot`, `stateRoot`, `logsRoot`, `globalFile`, `projectFile`, `parser`, `smokeTest`, `toolSmokeTest`, `OPENAI_API_BASE`, `OPENAI_MODEL`.
- Убедиться, что `settings.global.json` содержит `OPENAI_API_BASE` и `OPENAI_MODEL`, если используется внешний embedding provider.
- Убедиться, что `settings.global.json` содержит общие настройки parser/smoke.
- Убедиться, что build URL задан только в `mcp.build.url`.
- Убедиться, что production URL задан только в `mcp.production.url`.
- Проверить `settings.smokeTest.infrastructure.acceptableHttpStatusCodes`; для MCP endpoint обычно нужен `405`.
- Проверить `settings.smokeTest.infrastructure.logErrorPatterns`; не использовать слишком общий `ERROR`, лучше `Traceback`, `Unhandled exception`, `CRITICAL`.
- Для шумных build container предпочтительно задать `logTailLines` не меньше `2000`, а `logReadyPatterns` оставить пустым списком.
- Проверить, что `settings.smokeTest.profile=production` используется только при `settings.smokeTest.toolSmokeTest.enabled=true`.

## 3. Dry Run

```powershell
python .\update_mcp_project.py --config .\project.json --dry-run --verbose
```

Проверить:

- команда завершилась с `exit code 0`;
- config загрузился без validation errors;
- в логах виден derived repo path `<paths.root>/repo`;
- корректно определены `target_commit`, `last_indexed_commit`, `current_commit`, `previous_commit`;
- если repo раньше отсутствовал, локальный clone создан в `<paths.root>/repo`;
- source detection нашел ожидаемые `src/cf` и, при наличии, `src/cfe`.

## 4. First Real Update

```powershell
python .\update_mcp_project.py --config .\project.json --verbose
```

Проверить:

- если `<paths.root>/repo` раньше отсутствовал, локальный clone создан в `<paths.root>/repo`;
- создан `<paths.root>/staging/build`;
- создан `parser-config.json`;
- parser завершился допустимым exit code;
- появился `Report.txt`;
- report validation прошла успешно;
- build container поднялся;
- build infrastructure smoke-test прошел по `mcp.build.url`;
- build MCP tool smoke-test прошел по `mcp.build.url`;
- если build endpoint отвечает `405`, это разрешено в `acceptableHttpStatusCodes`;
- для самого первого deploy отсутствие `<paths.root>/staging/current`, `<paths.root>/chroma/current`, production container и `state/current_commit` считается нормой;
- после первого успешного deploy появились `<paths.root>/staging/current` и `<paths.root>/chroma/current`, а `state/previous_commit` все еще может отсутствовать.

## 5. Production Switch Validation

После успешного update проверить:

- `<paths.root>/staging/current` содержит новые metadata/code;
- `<paths.root>/chroma/current` содержит новый индекс;
- production container поднят на новом `current`;
- production infrastructure smoke-test прошел по `mcp.production.url`;
- production MCP tool smoke-test прошел по `mcp.production.url`, если `settings.smokeTest.toolSmokeTest.enabled=true`;
- `state/current_commit` обновился до нового commit;
- `state/last_indexed_commit` обновился до нового commit;
- `state/previous_commit` содержит предыдущий production commit, если он был.

## 6. Logs and Notifications

Проверить:

- в `<paths.root>/logs` появился update log;
- в `<paths.root>/logs` появился build container log;
- в `<paths.root>/logs` появился production container log;
- в логах нет значений из secrets files;
- при включенных notifications webhook получил expected payload;
- webhook берется из secret name `notifications.webhookUrlSecret`;
- payload содержит минимум `project`, `status`, `stage`, `targetCommit`, `lastIndexedCommit`, `logPath`.

## 7. No-Change Scenario

Повторно запустить ту же команду без новых коммитов:

```powershell
python .\update_mcp_project.py --config .\project.json
```

Проверить:

- updater корректно определяет `no changes`;
- повторный parser/docker/switch не запускается;
- команда завершается успешно.

## 8. Force Scenario

```powershell
python .\update_mcp_project.py --config .\project.json --force
```

Проверить:

- reindex запускается даже при совпадающем `last_indexed_commit`;
- build и production pipeline выполняются полностью.

## 9. Rollback Scenario

Подготовка:

- убедиться, что существуют `<paths.root>/staging/current` и `<paths.root>/staging/previous`;
- убедиться, что существуют `<paths.root>/chroma/current` и `<paths.root>/chroma/previous`;
- убедиться, что в state есть `current_commit` и `previous_commit`.

Запуск:

```powershell
python .\update_mcp_project.py --config .\project.json --rollback --verbose
```

Проверить:

- `current` и `previous` поменялись местами;
- production container стартовал на rollback-состоянии;
- production smoke-test прошел по `mcp.production.url`;
- `state/current_commit` и `state/previous_commit` поменялись местами;
- `state/last_indexed_commit` не изменился автоматически.

## 10. Promote Existing Build Scenario

Использовать, если updater завершился по `settings.smokeTest.toolSmokeTest.timeoutSeconds`, но build container продолжил long-running индексацию и позже стал готов.

Подготовка:

- убедиться, что `<paths.root>/staging/build` существует;
- убедиться, что `<paths.root>/chroma/build` существует;
- убедиться, что build container доступен по `mcp.build.url`;
- дождаться в build log строки `Phase 2/3 (code) done` или `Background indexing: phase 'code' completed`;
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
- `chroma/build` стал `chroma/current`;
- production smoke-test прошел по `mcp.production.url`;
- `state/current_commit` и `state/last_indexed_commit` равны promoted commit;
- `state/last_source_fingerprint` и `state/last_report_hash` записаны.

## 11. Failure and Automatic Rollback Drill

Проводить этот drill только после того, как уже существует rollback baseline, то есть `previous` artifacts и `state/previous_commit`. Для самого первого deploy automatic rollback невозможен.

Для controlled drill искусственно сломать production smoke-test:

- указать невалидный `mcp.production.url`; или
- временно сломать production readiness condition.

Проверить:

- production smoke-test падает;
- запускается automatic rollback;
- production возвращается на предыдущий рабочий индекс;
- `last_indexed_commit` не обновляется на неуспешный commit;
- при `rollback.preserveFailedIndex=true` сохраняется `failed-<timestamp>`;
- failure/rollback notification отправляется, если включена.

## 12. Exit Codes

Проверить руками минимум:

- `0` - успешный update;
- `1` - update или rollback успешен, но notification не отправилась;
- `2` - сломан config или settings;
- `11` - Docker недоступен;
- `15` - production smoke-test failed;
- `16` - rollback failed.

## 13. Sign-Off

Готово к боевому использованию, если:

- dry-run проходит стабильно;
- минимум один полный update проходит успешно;
- manual rollback проходит успешно;
- automatic rollback drill подтвержден для сценария, где уже существует `previous` baseline;
- logs и notifications соответствуют ожиданиям;
- state files корректно отражают текущее production-состояние.
