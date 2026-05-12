# MCP Project Updater Implementation Plan

Статус обновляется по мере реализации.

## Phase 1. Skeleton and Core CLI

- [x] Создать структуру пакета `mcp_project_updater/`
- [x] Создать entrypoint `update_mcp_project.py`
- [x] Создать entrypoint `mcp_smoke_test.py`
- [x] Создать PowerShell wrapper `update-mcp-project.ps1`
- [x] Реализовать `constants.py`, `errors.py`, `config.py`, `logging_setup.py`, `cli.py`
- [x] Реализовать базовые exit codes
- [x] Добавить стартовые unit tests для config и CLI

## Phase 2. State, Lock, Git, Source Detection

- [x] Реализовать `state.py`
- [x] Реализовать `lock.py`
- [x] Реализовать `git_ops.py`
- [x] Реализовать `source_detector.py`
- [x] Реализовать `--force`, `--no-git-pull`, `--dry-run`

## Phase 3. Staging, Parser, Report

- [x] Реализовать `staging.py`
- [x] Реализовать `parser_runner.py`
- [x] Реализовать `report_validator.py`
- [x] Подготовить `code/cf` и `code/cfe`

## Phase 4. Docker and Infrastructure Smoke

- [ ] Реализовать `docker_ops.py`
- [ ] Реализовать `mcp_container.py`
- [ ] Реализовать `smoke_infrastructure.py`
- [ ] Сохранять docker logs в отдельные файлы

## Phase 5. MCP Tool Smoke

- [ ] Реализовать пакет `mcp_smoke_test/`
- [ ] Реализовать `smoke_tool.py`
- [ ] Поддержать `tools/list`, `metadatasearch`, `codesearch`

## Phase 6. Production Switch and Rollback

- [ ] Реализовать `switcher.py`
- [ ] Реализовать `rollback.py`
- [ ] Реализовать `run_production_smoke_test(...)`
- [ ] Реализовать automatic rollback
- [ ] Реализовать manual rollback

## Phase 7. Notifications and Retention

- [ ] Реализовать `notifications.py`
- [ ] Реализовать retention cleanup
- [ ] Замаскировать секреты в логах

## Phase 8. Orchestration and Test Coverage

- [ ] Собрать `run_update(...)`
- [ ] Собрать `run_rollback(...)`
- [x] Добавить unit tests
- [ ] Добавить integration-style tests с mock command runners
- [x] Обновить план по факту реализации
