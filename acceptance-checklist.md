# MCP Project Updater Acceptance Checklist

Этот checklist нужен для первого реального запуска не на моках, а на настоящем parser, Docker и MCP image.

## 1. Preflight

- Убедиться, что Python `3.11+`, `git` и `docker` доступны в `PATH`
- Проверить, что parser tool существует по пути из `parser.toolPath`
- Проверить, что Git repo по `repo.path` существует и содержит ожидаемые исходники
- если `repo.path` ещё не существует, проверить корректность `repo.cloneUrl`
- если используется GitLab token auth, проверить наличие env из `repo.auth.tokenEnv`
- Проверить, что `mcp.production.containerName` и `mcp.build.containerName` уникальны
- Проверить, что `mcp.production.hostPort` и `mcp.build.hostPort` не конфликтуют
- Проверить, что каталогам `stagingRoot`, `chromaRoot`, `stateRoot`, `logsRoot` можно писать
- Проверить, что все env из `mcp.secretEnv` экспортированы в окружение
- Если включены notifications, проверить наличие env из `notifications.webhookUrlEnv`

## 2. Config Sanity

- Создать рабочий `project.json` на основе [project.example.json](./project.example.json)
- Для первого прогона выставить корректные:
  - `repo.path`
  - `repo.cloneUrl`
  - `parser.toolPath`
  - `mcp.image`
  - `mcp.production.url`
  - `mcp.build.url`
  - `smokeTest.toolSmokeTest.toolPath`
- Проверить, что `smokeTest.profile=production` только если `toolSmokeTest.enabled=true`

## 3. Dry Run

Запустить:

```powershell
python .\update_mcp_project.py --config .\project.json --dry-run --verbose
```

Проверить:

- команда завершилась с `exit code 0`
- config загрузился без validation errors
- корректно определились `target_commit`, `last_indexed_commit`, `current_commit`, `previous_commit`
- если repo раньше отсутствовал, локальный mirror был создан в `repo.path`
- source detection нашёл ожидаемые `src/cf` и, при наличии, `src/cfe`
- build и production URL в логе соответствуют реальной среде

## 4. First Real Update

Запустить:

```powershell
python .\update_mcp_project.py --config .\project.json --verbose
```

Проверить:

- создан `staging/build`
- создан `parser-config.json`
- parser завершился допустимым exit code
- появился `Report.txt`
- report validation прошла успешно
- build container поднялся
- build infrastructure smoke-test прошёл
- build MCP tool smoke-test прошёл

## 5. Production Switch Validation

После успешного update проверить:

- `staging/current` содержит новый metadata/code
- `chroma/current` содержит новый индекс
- production container поднят на новом `current`
- production smoke-test прошёл по `mcp.production.url`
- `state/current_commit` обновился до нового commit
- `state/last_indexed_commit` обновился до нового commit
- `state/previous_commit` содержит предыдущий production commit, если он был

## 6. Logs and Notifications

Проверить:

- в `logsRoot` появился update log
- в `logsRoot` появился build container log
- в `logsRoot` появился production container log
- в логах нет значений из secret env
- при включённых notifications webhook получил expected payload

## 7. No-Change Scenario

Повторно запустить ту же команду без новых коммитов:

```powershell
python .\update_mcp_project.py --config .\project.json
```

Проверить:

- updater корректно определяет `no changes`
- повторный parser/docker/switch не запускается
- команда завершается успешно

## 8. Force Scenario

Запустить:

```powershell
python .\update_mcp_project.py --config .\project.json --force
```

Проверить:

- reindex запускается даже при совпадающем `last_indexed_commit`
- build и production pipeline выполняются полностью

## 9. Rollback Scenario

Подготовка:

- убедиться, что существуют `staging/current` и `staging/previous`
- убедиться, что существуют `chroma/current` и `chroma/previous`
- убедиться, что в state есть `current_commit` и `previous_commit`

Запустить:

```powershell
python .\update_mcp_project.py --config .\project.json --rollback --verbose
```

Проверить:

- `current` и `previous` поменялись местами
- production container стартовал на rollback-состоянии
- production smoke-test после rollback прошёл
- `state/current_commit` и `state/previous_commit` поменялись местами

## 10. Failure and Automatic Rollback Drill

Для controlled drill искусственно сломать production smoke-test:

- указать невалидный `mcp.production.url`
или
- временно сломать production readiness condition

Запустить обычный update и проверить:

- production smoke-test падает
- запускается automatic rollback
- production возвращается на предыдущий рабочий индекс
- `last_indexed_commit` не обновляется на неуспешный commit
- при `rollback.preserveFailedIndex=true` сохраняется `failed-<timestamp>`
- отправляется failure/rollback notification, если они включены

## 11. Exit Codes

Проверить руками хотя бы эти сценарии:

- `0` — успешный update
- `1` — update успешен, но `onSuccess` notification не отправилась
- `2` — сломан `project.json`
- `11` — Docker недоступен
- `15` — production smoke-test failed
- `16` — rollback failed

## 12. Sign-Off

Готово к боевому использованию, если:

- dry-run проходит стабильно
- минимум один полный update проходит успешно
- manual rollback проходит успешно
- automatic rollback drill подтверждён
- логи и notifications соответствуют ожиданиям
- state файлы корректно отражают текущее production-состояние
