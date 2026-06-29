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

`paths.root` является optional override. Если он не задан, resolved `paths.root` равен parent directory `project.json`. `settings.global.json` читается из `paths.root.parent`.

`settings.global.json` может содержать `projectDefaults`:

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

`mcp.indexStorageRoot` может быть explicit в project config или derived из `settings.projectDefaults.indexStorageRootTemplate`.

`mcp.hostPort` является compact alias для production host port. Resolution order:

1. `mcp.production.hostPort`, если задан.
2. `mcp.hostPort`, если `mcp.production.hostPort` не задан.
3. Если оба заданы и отличаются, `ConfigValidationError`.

Если `mcp.build.hostPort` не задан, build port = production host port + `settings.projectDefaults.buildHostPortOffset`.

Если `mcp.production.url` / `mcp.build.url` не заданы, URL строится как `{urlScheme}://{urlHost}:{hostPort}{urlPath}`.

Если `mcp.production.containerName` / `mcp.build.containerName` не заданы, используются templates `mcp-{project}` и `mcp-{project}-build`.

Common MCP flags optional defaults:

- `indexCode=true`
- `indexMetadata=true`
- `indexHelp=false`
- `resetDatabaseOnBuild=true`
- `resetCache=false`
- `useSse=false`
- `useGpu=false`

`MCPConfig` содержит:

```python
index_container_path: str = "/app/chroma_db"
```

`mcp.indexContainerPath` опционален. Если он задан, config validation требует absolute Unix-style container path без Windows drive/backslash syntax.

`settings.mcp.secretEnv` используется для универсальных MCP secrets, например `LICENSE_KEY`. Проектные `mcp.env` и `mcp.secretEnv` используются для опциональных OpenAI/OpenRouter параметров конкретного проекта. `OPENAI_API_BASE`, `OPENAI_MODEL` и `OPENAI_API_KEY` не должны быть глобально обязательными: если project config не задает эти поля, validation не требует `OPENROUTER_API_KEY`, а Docker command не должен содержать `OPENAI_API_BASE`, `OPENAI_MODEL`, `OPENAI_API_KEY`.

Validation:

- missing explicit `mcp.indexStorageRoot` and missing `settings.projectDefaults.indexStorageRootTemplate` -> `ConfigValidationError`;
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

Tool smoke config payload должен содержать:

```json
{
  "requireMetadataVectorIndex": true,
  "requireCodeVectorIndex": true
}
```

Значения выводятся из `mcp.indexMetadata` и `mcp.indexCode`. Smoke client должен вызывать MCP tool `stats` и проверять `stats.collections.metadata > 0` для metadata index и `stats.collections.code > 0` для code index. Для `metadatasearch` и `codesearch` успешный ответ должен иметь `search_layer=vector+bm25`; fallback layers вроде `grep` не проходят строгий smoke.

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
    repair_metadata_index: bool = False
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

`--repair-metadata-index` запрещен вместе с:

- `--force`
- `--storage-migration`
- `--rollback`
- `--promote-existing-build`
- `--dry-run`

`--force` не является migration marker. Это только rebuild control текущего configured `mcp.indexStorageRoot`.

PowerShell wrapper `update-mcp-project.ps1` должен прокидывать `-StorageMigration` в `--storage-migration` и `-RepairMetadataIndex` в `--repair-metadata-index`.

## 5. Container Commands

Host-side storage path:

- build: `paths.index_storage_root / "build"`
- production: `paths.index_storage_root / "current"`

Container mount target берется из `mcp.indexContainerPath`, default `/app/chroma_db`:

```text
-v <index_storage_path>:<mcp.indexContainerPath>
```

Build container command использует configured build indexing flags:

```text
INDEX_METADATA=<mcp.indexMetadata>
INDEX_CODE=<mcp.indexCode>
INDEX_HELP=<mcp.indexHelp>
```

Production container command hardcodes indexing disabled:

```text
RESET_DATABASE=false
INDEX_METADATA=false
INDEX_CODE=false
INDEX_HELP=false
REINDEX_INTERVAL_SEC=0
```

Это относится к обычному switch, storage migration switch и rollback production start. Production container должен только обслуживать готовый `index_storage_root/current`. `REINDEX_INTERVAL_SEC=0` отключает periodic scheduler внутри MCP image; `BACKGROUND_INDEXING=false` не используется, потому что в текущем образе это включает legacy startup indexing path.

Updater не добавляет automatic `docker pull`. Обновление image является manual prerequisite.

## 6. Build Storage Preparation

Функция подготовки build storage:

```python
def prepare_index_storage_build(index_storage_root: Path, *, seed_source: Path | None = None) -> Path:
    ...
```

Поведение:

- удалить существующий `build` через общий guarded cleanup внутри `index_storage_root`;
- если `seed_source` задан и существует, скопировать его в `build`;
- иначе создать пустой `build`.

Cleanup `index_storage_root/build` для WSL UNC paths (`\\wsl.localhost\<distro>\...` и `\\wsl$\<distro>\...`) должен выполняться через `wsl.exe -d <distro> -u root -- rm -rf -- <linux-path>`, а не через Windows `shutil.rmtree()`. Root user внутри WSL нужен для файлов, созданных Docker container-ом от root. Ошибки cleanup должны превращаться в `UpdaterError` с `ExitCode.BUILD_CONTAINER_FAILED`, чтобы CLI возвращал code `13` без raw traceback.

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
- нет `--repair-metadata-index`;
- current report существует;
- current index storage существует;
- fingerprint/commit/hash условия совпали.

Reuse current storage:

```python
reuse_current_index_storage = (
    options.repair_metadata_index
    or (not options.force and not options.storage_migration and current_index_storage_exists)
)
```

Metadata unchanged:

```python
metadata_unchanged = (
    not options.force
    and not options.storage_migration
    and not options.repair_metadata_index
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
    index_metadata=True if options.repair_metadata_index else (False if metadata_unchanged else None),
    index_code=False if options.repair_metadata_index else None,
    index_help=False if options.repair_metadata_index else None,
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

## 9. Metadata Repair Mode

`--repair-metadata-index`:

- отключает skip по совпавшему state;
- требует существующий `index_storage_root/current` до запуска build container;
- seed-ит `index_storage_root/build` из `index_storage_root/current`;
- стартует build container с `RESET_DATABASE=false`, `INDEX_METADATA=true`, `INDEX_CODE=false`, `INDEX_HELP=false`;
- после build infrastructure smoke вызывает MCP tool `reindex(force=true)` на build URL;
- ожидает завершения repair через `stats`;
- требует `stats.collections.metadata > 0`;
- если `mcp.indexCode=true`, требует `stats.collections.code > 0`, чтобы подтвердить сохранение code index;
- затем выполняет обычный build tool smoke и общий production switch.

`reindex(force=true)` в этом режиме не должен вызываться на production. Безопасность `force=true` обеспечивается тем, что в build container отключены code/help phases.

## 10. Smoke Order

Общий порядок для update, storage migration и promote:

1. build infrastructure smoke-test;
2. build tool smoke-test;
3. production switch;
4. start production container;
5. production smoke-test;
6. state update.

Production smoke-test не должен запускаться до switch, потому production container еще старый или не запущен.

Для обычного update и promote build infrastructure smoke должен выполняться с `log_ready_patterns=[]`, даже если в settings заданы `logReadyPatterns`. Это не отключает `log_error_patterns`: ошибки в Docker logs остаются blocking. Готовность tools/indexes доказывается build tool smoke-test до production switch.

## 11. Switcher

`perform_switch(..., storage_migration: bool = False)`:

- проверяет `staging/build` и `index_storage_root/build`;
- удаляет production container;
- best-effort удаляет build container;
- удаляет старые `previous` artifacts через guarded cleanup внутри `staging_root` / `index_storage_root`;
- перемещает `current` в `previous`;
- перемещает `build` в `current`;
- стартует production container с disabled `INDEX_*` и `REINDEX_INTERVAL_SEC=0`;
- выполняет production smoke-test;
- записывает state только после успешного smoke.

Cleanup старого `index_storage_root/previous` использует тот же общий helper, что и build storage cleanup. Recursive cleanup должен отказываться удалять target, если target равен allowed root или находится вне allowed root. Ошибки cleanup должны превращаться в `ProductionSwitchError`, чтобы CLI возвращал exit code `14` без raw traceback.

При обычном production smoke failure:

- сохранить production logs;
- вызвать `perform_automatic_rollback`;
- выбросить `ProductionSmokeTestFailed(..., rollback_attempted=True)`.

При `storage_migration=True` и production smoke failure:

- сохранить production logs;
- остановить неисправный production container через `docker stop`;
- не вызывать automatic rollback;
- выбросить `ProductionSmokeTestFailed(..., rollback_attempted=False)` с manual recovery guidance.

## 12. Rollback

Rollback использует `paths.index_storage_root`:

- automatic rollback: `current` -> `failed-<timestamp>` или удалить, `previous` -> `current`;
- manual rollback: swap `current` и `previous`;
- production container стартует после перемещения storage;
- production smoke-test обязателен.

Automatic rollback не применяется в storage migration.

## 13. Promote Existing Build

`--promote-existing-build` требует:

- `paths.staging_root / "build"`
- `paths.index_storage_root / "build"`

Promote выполняет build smoke-tests, затем вызывает общий `perform_switch`.

`promote-existing-build.ps1`:

- принимает `-UpdateLog` как optional override;
- если `-UpdateLog` не указан, вычисляет resolved project root: `paths.root` из project config или директорию `project.json`, если `paths.root` отсутствует;
- выбирает самый поздний по timestamp в имени `YYYYMMDD-HHMMSS-update.log` из `<resolved-root>/logs`;
- извлекает из log `Target commit:`, `Source fingerprint:` и `Report hash:`.

## 14. Tests

Обязательные тестовые области:

- missing explicit `mcp.indexStorageRoot` and missing `settings.projectDefaults.indexStorageRootTemplate`;
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

## 15. Documentation

Docs/examples must state:

- explicit `mcp.indexStorageRoot` or `settings.projectDefaults.indexStorageRootTemplate` is required;
- `mcp.indexContainerPath` defaults to `/app/chroma_db` for CodeMetadata;
- Windows storage root must be WSL-mounted;
- Linux storage root must be absolute native path;
- `docker pull` is manual prerequisite;
- `--storage-migration` is the migration marker;
- `--force` is not a migration marker;
- old ChromaDB database must not seed zvec build;
- storage migration production smoke failure uses manual recovery;
- beta/arm64 images are not supported.

## 16. Verification

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
