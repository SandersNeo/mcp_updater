# MCP Project Updater

`mcp-project-updater` обновляет индексы MCP-проекта из Git-репозитория, прогоняет staging/build pipeline, выполняет build и production smoke-tests, переключает production на новый индекс и умеет делать rollback.

Репозиторий содержит:

- `update_mcp_project.py` — основной CLI для update и manual rollback
- `mcp_smoke_test.py` — отдельный CLI для MCP tool smoke-test
- `mcp_project_updater/` — основная логика updater-а
- `mcp_smoke_test/` — клиент и CLI для smoke-проверки MCP tools
- `tests/` — unit и integration-style тесты

## Что уже реализовано

- загрузка и валидация `project.json`
- lock/state management
- работа с Git target commit
- source detection для `src/cf` и `src/cfe`
- staging + parser config generation + report validation
- build container startup
- infrastructure smoke-test
- MCP tool smoke-test
- production switch
- automatic rollback и manual rollback
- notifications + log retention cleanup
- orchestration workflow с тестовым покрытием

## Требования

- Python `3.11+`
- Docker
- Git
- внешний parser tool, путь к которому указывается в `project.json`
- секреты из `mcp.secretEnv` должны быть доступны в переменных окружения
- если репозиторий берётся из GitLab по HTTPS, должен быть доступен token из `repo.auth.tokenEnv`

## Установка

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e .
```

Для Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
```

## Основной запуск

```powershell
python .\update_mcp_project.py --config .\project.json
```

Поддерживаемые флаги:

- `--config` — путь к `project.json`
- `--force` — переиндексировать даже если `target_commit == last_indexed_commit`
- `--no-git-pull` — использовать текущий `HEAD` без `fetch/pull`
- `--rollback` — выполнить manual rollback `current <-> previous`
- `--promote-existing-build` — принять уже существующий `staging/build` и `chroma/build` без повторного parser/build этапа
- `--promote-commit` — явно задать commit, который будет записан в state при `--promote-existing-build`
- `--promote-source-fingerprint` — явно задать source fingerprint для state при `--promote-existing-build`
- `--promote-report-hash` — явно задать report hash для state при `--promote-existing-build`
- `--verbose` — более подробный лог
- `--dry-run` — только валидация и расчёт плана без parser/docker/switch

PowerShell wrapper:

```powershell
.\update-mcp-project.ps1 -ConfigPath .\project.json
```

## GitLab Source Model

Updater работает не через GitLab API, а через обычный `git clone / fetch / pull`.

Это значит:

- `repo.path` — локальный mirror-каталог, с которым дальше работает updater
- если `repo.path` уже существует, updater обновляет его через `fetch/pull`
- если `repo.path` ещё не существует, updater клонирует репозиторий из `repo.cloneUrl`
- для GitLab over HTTPS можно задать `repo.auth.type=gitlab-token` и `repo.auth.tokenEnv`

Рекомендуемый layout для одного проекта:

```text
C:/mcp-updater-data/<project>/
  repo/
  staging/
  chroma/
  state/
  logs/
```

Так все данные конкретного MCP-проекта лежат под одним корнем, а `repo.path` не смешивается с артефактами других проектов.

Минимальная схема для GitLab:

```json
{
  "repo": {
    "path": "C:/mcp-updater-data/orders/repo",
    "branch": "master",
    "remote": "origin",
    "pullMode": "ff-only",
    "cloneUrl": "https://gitlab.example.com/team/orders.git",
    "auth": {
      "type": "gitlab-token",
      "tokenEnv": "GITLAB_TOKEN",
      "username": "oauth2"
    }
  }
}
```

## Notifications and `MCP_UPDATE_WEBHOOK_URL`

Notifications настраиваются в блоке `notifications` внутри `project.json`.

Ключевые поля:

- `notifications.enabled`
- `notifications.onSuccess`
- `notifications.onFailure`
- `notifications.onRollback`
- `notifications.webhookUrlEnv`

В типовом конфиге `notifications.webhookUrlEnv` указывает на `MCP_UPDATE_WEBHOOK_URL`.

Что это значит:

- updater не хранит webhook URL прямо в `project.json`
- updater читает имя env-переменной из `notifications.webhookUrlEnv`
- затем берёт фактический webhook URL из переменной окружения, например `MCP_UPDATE_WEBHOOK_URL`

Типовой пример:

```json
{
  "notifications": {
    "enabled": true,
    "onSuccess": true,
    "onFailure": true,
    "onRollback": true,
    "webhookUrlEnv": "MCP_UPDATE_WEBHOOK_URL"
  }
}
```

Пример установки переменной в PowerShell:

```powershell
$env:MCP_UPDATE_WEBHOOK_URL = "https://hooks.example.com/mcp-updater"
```

Когда переменная обязательна:

- если `notifications.enabled=false`, она не нужна
- если notifications включены и реально вызывается отправка webhook, переменная должна существовать в окружении
- на практике её нужно задавать всегда, если `notifications.enabled=true`

Какой payload отправляется в webhook:

- `project`
- `status`
- `stage`
- `targetCommit`
- `lastIndexedCommit`
- `productionUntouched`
- `rollbackAttempted`
- `rollbackSuccess`
- `logPath`

Семантика статусов:

- `status=success` — update завершился успешно
- `status=failed` — update завершился ошибкой
- `status=rollback` — был manual rollback или automatic rollback path

Важно:

- значение `MCP_UPDATE_WEBHOOK_URL` не логируется как plain text
- ошибка отправки notification не должна маскировать основной статус workflow
- `update success + notification failed` -> `exit code 1`
- `failed update + notification failed` -> сохраняется исходный код ошибки update
- `rollback success + notification failed` -> `exit code 1`
- `rollback failed + notification failed` -> сохраняется исходный код rollback

## MCP Smoke Test

Отдельный smoke-test runner можно запускать напрямую:

```powershell
python .\mcp_smoke_test.py --config .\project.json
```

Он проверяет:

- `tools/list`
- metadata tool, по умолчанию `metadatasearch`
- code tool, по умолчанию `codesearch`

Названия tools и имена аргументов настраиваются в `smokeTest.toolSmokeTest`.
Для временной диагностики можно включить `smokeTest.toolSmokeTest.diagnostic=true`: тогда `mcp_smoke_test.py` будет писать в `stderr`, на каком шаге он находится (`connect`, `initialize`, `list_tools`, `call_tool`).

Для долгой индексации tool smoke работает по модели `общий дедлайн + короткие попытки`:

- `timeoutSeconds` — общий лимит ожидания readiness code/metadata tools
- `attemptTimeoutSeconds` — лимит одной попытки `mcp_smoke_test.py`
- `retryIntervalSeconds` — пауза между повторными попытками после timeout

Это безопаснее, чем один `codesearch` на несколько часов: зависший запрос не держится бесконечно, а updater периодически перепроверяет готовность индекса.
В коде сейчас нет жёсткого верхнего лимита для `smokeTest.toolSmokeTest.timeoutSeconds`, поэтому для больших конфигураций можно ставить и `54000` секунд (15 часов), и больше, если это соответствует реальному профилю индексации.

## Infrastructure Smoke Configuration

Infrastructure smoke-test не использует отдельный `httpReadyUrl`.

Реальная модель такая:

- build infrastructure smoke ходит в `mcp.build.url`
- production infrastructure smoke ходит в `mcp.production.url`

Поле `smokeTest.infrastructure.acceptableHttpStatusCodes` задаёт, какие HTTP статусы считаются нормальным ответом readiness endpoint.

Для MCP endpoint это важно, потому что `GET /mcp` нередко отвечает не `200`, а `405 Method Not Allowed`. Это не обязательно означает проблему контейнера: сервер может быть уже поднят, но не поддерживать `GET` на MCP endpoint.

Практически безопасный набор для MCP readiness-check:

```json
"acceptableHttpStatusCodes": [200, 400, 404, 405]
```

Для `smokeTest.infrastructure.logErrorPatterns` не стоит использовать слишком общий паттерн вроде `ERROR`.
Некоторые MCP images пишут `ERROR` и в recoverable сценариях, например при fallback определения кодировки `Report.txt`, после чего продолжают нормальную индексацию.
Безопаснее использовать более узкие признаки реальной аварии, например:

```json
"logErrorPatterns": ["Traceback", "Unhandled exception", "CRITICAL"]
```

Если в старом локальном конфиге ещё есть `smokeTest.infrastructure.httpReadyUrl`, updater его больше не использует. Источник истины для readiness URL — это `mcp.build.url` и `mcp.production.url`.

## Workflow update

Основной `update` выполняет такие этапы:

1. Берёт lock и читает state.
2. Валидирует repo и определяет `target_commit`.
3. Проверяет наличие `src/cf` и `src/cfe`.
4. Готовит `staging/build`.
5. Генерирует `parser-config.json` и запускает parser.
6. Валидирует `Report.txt`.
7. Подготавливает `code/cf` и `code/cfe`.
8. Поднимает build container.
9. Выполняет build infrastructure smoke-test.
10. Выполняет build MCP tool smoke-test по `mcp.build.url`, если он включён.
11. Переключает `build -> current`.
12. Поднимает production container.
13. Выполняет production smoke-test:
    production infrastructure smoke-test
    +
    production MCP tool smoke-test по `mcp.production.url`, если `smokeTest.toolSmokeTest.enabled=true`
14. При ошибке production smoke-test запускает automatic rollback.
15. Обновляет state и отправляет notifications.

## Optimization Model

Updater использует два уровня пропуска/оптимизации:

- `target_commit == last_indexed_commit` и нет `--force` -> весь update пропускается сразу
- `source fingerprint == last_source_fingerprint` и текущие production artifacts существуют -> update тоже пропускается, даже если commit новый, но 1С-исходники реально не изменились

Если parser всё же был запущен, updater дополнительно считает `report hash`:

- `report hash == last_report_hash` -> metadata считается неизменившейся
- в этом режиме build стартует не с пустого `chroma/build`, а с копии `chroma/current`
- build container запускается с `RESET_DATABASE=false` и `INDEX_METADATA=false`
- это позволяет не переиндексировать `metadatasearch`, если изменилась только code-часть

## Promote Existing Build

`--promote-existing-build` нужен для длинных initial builds, когда updater уже завершился по timeout, но build container продолжил индексацию и позже дошёл до готового состояния.

Режим не запускает parser, не пересоздаёт `staging/build`, не очищает `chroma/build` и не стартует новый build container. Он:

- проверяет существующие `staging/build` и `chroma/build`
- валидирует `staging/build/metadata/Report.txt`
- прогоняет build infrastructure smoke-test по `mcp.build.url`
- прогоняет build MCP tool smoke-test по `mcp.build.url`, если он включён
- сохраняет build container log
- выполняет штатный switch `build -> current`
- поднимает production container
- прогоняет production smoke-test по `mcp.production.url`
- записывает `current_commit`, `last_indexed_commit`, `last_source_fingerprint`, `last_report_hash`

Перед запуском нужно дождаться завершения code phase в build log:

```powershell
docker logs --tail 300 mcp-orders-build 2>&1 | Select-String -Pattern "Phase 2/3 \(code\) done|Background indexing: phase 'code' completed|code progress"
```

После этого можно принять build:

```powershell
python .\update_mcp_project.py `
  --config .\project.orders.json `
  --promote-existing-build `
  --promote-commit 4315fdf7efb6e1f09876561150f7dc0390ea6b44 `
  --promote-source-fingerprint 904308bd3eb4b34dcaf502cc84c64f7043e5138cc972e851011d4697303ab914 `
  --promote-report-hash 24951b4aea3aca150414ff08809755a4d59dd8d83ca5ab331a8ee4e919b0db1c `
  --verbose
```

Если `--promote-commit`, `--promote-source-fingerprint` или `--promote-report-hash` не указаны, updater вычислит их из текущего Git checkout и существующего `Report.txt`. Для восстановления после timeout надёжнее передавать значения из failed update log, чтобы state точно соответствовал уже построенному build.

## Workflow rollback

`--rollback` выполняет manual rollback:

- меняет местами `staging/current` и `staging/previous`
- меняет местами `chroma/current` и `chroma/previous`
- поднимает production container на `previous`
- прогоняет production smoke-test: infrastructure + tool smoke по `mcp.production.url`, если tool smoke включён
- обновляет `current_commit` и `previous_commit`
- не переписывает `last_indexed_commit` автоматически

## Структура конфигурации

`project.json` должен содержать как минимум такие блоки:

- `project`
- `repo`
- `sources`
- `parser`
- `mcp`
- `paths`
- `smokeTest`
- `notifications`
- `retention`
- `rollback`

Ключевые поля:

- `repo.path`, `repo.branch`, `repo.remote`
- `repo.cloneUrl`
- `repo.auth.type`, `repo.auth.tokenEnv`, `repo.auth.username`
- `sources.mainConfigPath`, `sources.extensionPath`
- `parser.toolPath`
- `mcp.production.*` и `mcp.build.*`
- `mcp.secretEnv`
- `paths.stagingRoot`, `paths.chromaRoot`, `paths.stateRoot`, `paths.logsRoot`
- `smokeTest.infrastructure.*`
- `smokeTest.toolSmokeTest.*`
- `notifications.webhookUrlEnv`

Ограничения, которые уже валидируются:

- production и build container names должны отличаться
- production и build ports должны отличаться
- `smokeTest.profile` должен быть `dev` или `production`
- при `smokeTest.profile=production` нельзя выключать `toolSmokeTest.enabled`
- если `repo.path` ещё не существует, должен быть задан `repo.cloneUrl`
- `repo.auth.type` должен быть `none` или `gitlab-token`
- при `repo.auth.type=gitlab-token` должен быть задан `repo.auth.tokenEnv`

Готовый шаблон конфига: [project.example.json](./project.example.json)

## Exit codes

Основные коды возврата:

- `0` — success
- `1` — success with warnings
- `2` — config error
- `5` — git pull failed
- `9` — parser failed
- `10` — report validation failed
- `11` — docker unavailable
- `13` — build smoke failed
- `14` — production switch failed
- `15` — production smoke failed
- `16` — rollback failed

Полный список находится в [mcp_project_updater/constants.py](./mcp_project_updater/constants.py).

Семантика notifications в основном workflow:

- `update success + notification failed` -> `1`
- `manual rollback success + notification failed` -> `1`
- `update failed + notification failed` -> сохраняется исходный код ошибки update
- `rollback failed + notification failed` -> сохраняется исходный код rollback

## Тесты

```powershell
pytest -q
```

На текущем состоянии репозитория тестовый набор зелёный.

## Документация

- [prd-mcp-project-updater.md](./prd-mcp-project-updater.md)
- [dev-spec-mcp-project-updater.md](./dev-spec-mcp-project-updater.md)
- [implementation-plan-mcp-project-updater.md](./implementation-plan-mcp-project-updater.md)
- [acceptance-checklist.md](./acceptance-checklist.md)
