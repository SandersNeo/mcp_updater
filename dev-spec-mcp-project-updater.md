# Dev Spec: MCP Project Updater

## 1. Scope

Реализация updater должна поддерживать zvec-backed CodeMetadata MCP с текущим default container interface:

- `/app/metadata`
- `/app/code`
- `/app/chroma_db` как default index storage mount target
- port `8000`
- stable images `comol/1c_code_metadata_mcp:light` и `comol/1c_code_metadata_mcp:latest`

Внутренний формат index storage для updater непрозрачен.
Container mount target не выводится из backend name: `zvec` не означает автоматический переход на `/app/zvec_db`.

## 2. Config Model

`PathsConfig`:

```python
@dataclass(slots=True)
class PathsConfig:
    root: Path
    staging_root: Path
    index_storage_root: Path
    state_root: Path
    logs_root: Path

    @property
    def chroma_root(self) -> Path:
        return self.index_storage_root
```

`chroma_root` остается только compatibility alias. Новая логика должна использовать `index_storage_root`.

`mcp.indexStorageRoot` обязателен для каждого project config.

`MCPConfig` содержит:

```python
index_container_path: str = "/app/chroma_db"
```

`mcp.indexContainerPath` опционален. Если он задан, config validation требует absolute Unix-style container path без Windows drive/backslash syntax.

`settings.mcp.secretEnv` используется для универсальных MCP secrets, например `LICENSE_KEY`. Проектные `mcp.env` и `mcp.secretEnv` используются для опциональных OpenAI/OpenRouter параметров конкретного проекта. `OPENAI_API_BASE`, `OPENAI_MODEL` и `OPENAI_API_KEY` не должны быть глобально обязательными: если project config не задает эти поля, validation не требует `OPENROUTER_API_KEY`, а Docker command не должен содержать `OPENAI_API_BASE`, `OPENAI_MODEL`, `OPENAI_API_KEY`.

Validation:

- missing `mcp.indexStorageRoot` -> `ConfigValidationError`;
- Windows path должен начинаться с `\\wsl.localhost\` или `\\wsl$\`;
- Linux path должен быть absolute;
- storage path или parent должен быть доступен до Git/parser/Docker операций;
- `mcp.image` должен входить в stable allow-list.

## 3. Smoke Config Model

`InfrastructureSmokeConfig` использует:

```python
require_index_storage_not_empty: bool
```

Парсинг:

- сначала читать `settings.smokeTest.infrastructure.requireIndexStorageNotEmpty`;
- если новое имя отсутствует, читать legacy `requireChromaNotEmpty`;
- если оба отсутствуют, падать с ошибкой по `settings.smokeTest.infrastructure.requireIndexStorageNotEmpty`;
- если заданы оба, новое имя имеет приоритет.

Diagnostic messages должны использовать `MCP index storage path`.

## 4. CLI

`CliOptions`:

```python
@dataclass(slots=True)
class CliOptions:
    config_path: Path
    force: bool = False
    no_git_pull: bool = False
    rollback: bool = False
    promote_existing_build: bool = False
    storage_migration: bool = False
    promote_commit: str | None = None
    promote_source_fingerprint: str | None = None
    promote_report_hash: str | None = None
    verbose: bool = False
    dry_run: bool = False
```

`--storage-migration` запрещен вместе с:

- `--force`
- `--rollback`
- `--promote-existing-build`

`--force` не является migration marker. Это только rebuild control текущего configured `mcp.indexStorageRoot`.

PowerShell wrapper `update-mcp-project.ps1` должен прокидывать `-StorageMigration` в `--storage-migration`.

## 5. Container Commands

Host-side storage path:

- build: `paths.index_storage_root / "build"`
- production: `paths.index_storage_root / "current"`

Container mount target берется из `mcp.indexContainerPath`, default `/app/chroma_db`:

```text
-v <index_storage_path>:<mcp.indexContainerPath>
```

Updater не добавляет automatic `docker pull`. Обновление image является manual prerequisite.

## 6. Build Storage Preparation

Функция подготовки build storage:

```python
def prepare_index_storage_build(index_storage_root: Path, *, seed_source: Path | None = None) -> Path:
    ...
```

Поведение:

- удалить существующий `build`;
- если `seed_source` задан и существует, скопировать его в `build`;
- иначе создать пустой `build`.

Legacy `prepare_chroma_build` может остаться alias-ом на время совместимости.

## 7. Update Workflow

В `run_update`:

```python
current_index_storage_path = config.paths.index_storage_root / "current"
current_index_storage_exists = current_index_storage_path.exists()
```

Skip/no-change возможен только если:

- нет `--force`;
- нет `--storage-migration`;
- current report существует;
- current index storage существует;
- fingerprint/commit/hash условия совпали.

Reuse current storage:

```python
reuse_current_index_storage = (
    not options.force
    and not options.storage_migration
    and current_index_storage_exists
)
```

Metadata unchanged:

```python
metadata_unchanged = (
    not options.force
    and not options.storage_migration
    and report_hash == state_snapshot.last_report_hash
    and current_report_exists
    and current_index_storage_exists
)
```

Build start:

```python
start_build_container(
    ...,
    reset_database=False if reuse_current_index_storage else None,
    seed_index_storage_from=current_index_storage_path if reuse_current_index_storage else None,
    index_metadata=False if metadata_unchanged else None,
)
```

Workflow logs должны использовать backend-neutral wording: `MCP index storage baseline`, не `Chroma baseline`.

## 8. Storage Migration Mode

`--storage-migration`:

- отключает skip по совпавшему state;
- отключает seed/reuse из `mcp.indexStorageRoot/current`;
- не читает старый `<paths.root>/chroma/current`;
- передает `storage_migration=True` в `perform_switch`;
- запрещает automatic rollback при production smoke failure.

Старая ChromaDB database может быть только backup/manual recovery source.

## 9. Smoke Order

Общий порядок для update, storage migration и promote:

1. build infrastructure smoke-test;
2. build tool smoke-test;
3. production switch;
4. start production container;
5. production smoke-test;
6. state update.

Production smoke-test не должен запускаться до switch, потому production container еще старый или не запущен.

## 10. Switcher

`perform_switch(..., storage_migration: bool = False)`:

- проверяет `staging/build` и `index_storage_root/build`;
- удаляет production container;
- best-effort удаляет build container;
- перемещает `current` в `previous`;
- перемещает `build` в `current`;
- стартует production container;
- выполняет production smoke-test;
- записывает state только после успешного smoke.

При обычном production smoke failure:

- сохранить production logs;
- вызвать `perform_automatic_rollback`;
- выбросить `ProductionSmokeTestFailed(..., rollback_attempted=True)`.

При `storage_migration=True` и production smoke failure:

- сохранить production logs;
- остановить неисправный production container через `docker stop`;
- не вызывать automatic rollback;
- выбросить `ProductionSmokeTestFailed(..., rollback_attempted=False)` с manual recovery guidance.

## 11. Rollback

Rollback использует `paths.index_storage_root`:

- automatic rollback: `current` -> `failed-<timestamp>` или удалить, `previous` -> `current`;
- manual rollback: swap `current` и `previous`;
- production container стартует после перемещения storage;
- production smoke-test обязателен.

Automatic rollback не применяется в storage migration.

## 12. Promote Existing Build

`--promote-existing-build` требует:

- `paths.staging_root / "build"`
- `paths.index_storage_root / "build"`

Promote выполняет build smoke-tests, затем вызывает общий `perform_switch`.

`promote-existing-build.ps1`:

- принимает `-UpdateLog` как optional override;
- если `-UpdateLog` не указан, читает `paths.root` из project config;
- выбирает самый поздний по timestamp в имени `YYYYMMDD-HHMMSS-update.log` из `<paths.root>/logs`;
- извлекает из log `Target commit:`, `Source fingerprint:` и `Report hash:`.

## 13. Tests

Обязательные тестовые области:

- missing `mcp.indexStorageRoot`;
- Windows non-WSL path rejected;
- Windows WSL path accepted;
- Linux relative path rejected;
- Linux absolute path accepted;
- `mcp.indexContainerPath` default `/app/chroma_db`;
- `mcp.indexContainerPath` override `/app/zvec_db`;
- invalid `mcp.indexContainerPath` rejected;
- `chroma_root` alias equals `index_storage_root`;
- stable image allow-list excludes beta/arm64;
- `--storage-migration` parse and flag conflicts;
- no-seed storage migration build;
- normal incremental seed;
- force rebuild no-seed;
- production smoke failure without automatic rollback in migration;
- failed migration container stop;
- state update only after production smoke success;
- Docker command uses configured `mcp.indexContainerPath`;
- new smoke config name and legacy alias;
- backend-neutral log/diagnostic text.

## 14. Documentation

Docs/examples must state:

- `mcp.indexStorageRoot` is required;
- `mcp.indexContainerPath` defaults to `/app/chroma_db` for CodeMetadata;
- Windows storage root must be WSL-mounted;
- Linux storage root must be absolute native path;
- `docker pull` is manual prerequisite;
- `--storage-migration` is the migration marker;
- `--force` is not a migration marker;
- old ChromaDB database must not seed zvec build;
- storage migration production smoke failure uses manual recovery;
- beta/arm64 images are not supported.

## 15. Verification

Перед завершением:

```powershell
pytest -q
openspec validate support-zvec-codemetadata --json
```

Поиском проверить, что runtime logs/docs не содержат неверных Chroma-only формулировок вне исторического контекста. Допустимые оставшиеся упоминания:

- `/app/chroma_db` как default CodeMetadata container mount target;
- `/app/zvec_db` только как explicit `mcp.indexContainerPath` override для образа с таким контрактом;
- `chroma_root` как legacy compatibility alias;
- `requireChromaNotEmpty` как legacy compatibility alias;
- `ChromaDB -> zvec` как исторический migration context;
- старый `<paths.root>/chroma/current` только как backup/manual recovery source.
