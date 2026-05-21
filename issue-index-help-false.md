Title: `INDEX_HELP=false` does not skip help phase and help file classification

## Summary

When the container is started with `INDEX_HELP=false`, the MCP server still runs the `help` phase and performs full help file classification. In our environment this makes startup and periodic reindex significantly slower even though help indexing is disabled at the updater level.

Observed behavior suggests that `INDEX_HELP=false` disables only help embedding, but does not disable the help phase itself.

## Expected behavior

When `INDEX_HELP=false`:

- the container should skip the `help` phase entirely; or
- at minimum, it should skip help file classification and XSD-related work.

## Actual behavior

The container receives `INDEX_HELP=false`, but still enters:

- `Phase 3/3 (help)`
- help file classification
- and in earlier runs also XSD generation

## Evidence

Updater-side container env for production:

```text
INDEX_METADATA=true
INDEX_CODE=true
INDEX_HELP=false
RESET_DATABASE=false
```

This was verified with:

```powershell
docker inspect mcp-upp --format "{{range .Config.Env}}{{println .}}{{end}}" | Select-String "INDEX_HELP|INDEX_CODE|INDEX_METADATA|RESET_DATABASE"
```

Container log excerpt from `mcp-uat`:

```text
2026-05-21 06:52:01,365 - INFO - [__main__] - Background indexing started: phases=['metadata', 'code', 'help'] force_full=False
...
2026-05-21 07:48:45,912 - INFO - [file_tracker] - File classification for 'help': new=0, modified=0, unchanged=1715, deleted=0
2026-05-21 07:48:45,913 - INFO - [vectorindexer.indexer] - Phase 3/3 (help): classify new=0 modified=0 unchanged=1715 deleted=0 → 0 to embed
2026-05-21 07:48:45,914 - INFO - [vectorindexer.indexer] - Phase 3/3 (help): nothing to (re-)embed (pending=0)
```

In previous runs we also observed XSD generation inside the help phase even when help content had not changed:

```text
Generated XSD: form.xsd
Generated XSD: dcs.xsd
Generated XSD: template.xsd
```

## Why this is a problem

- `help` changes very rarely in our projects.
- We explicitly set `indexHelp=false` in project configuration.
- Even with incremental indexing and Chroma reuse, full help file classification still runs and adds substantial latency.

## Reproduction

1. Start container with `INDEX_HELP=false`.
2. Ensure existing Chroma DB and file tracker are present.
3. Start MCP server with background indexing enabled.
4. Observe logs.

Expected:

- no `help` phase

Actual:

- `help` phase still starts
- help files are classified
- additional help-related work may still run

## Request

Please clarify intended semantics of `INDEX_HELP=false`.

If the intent is "disable help indexing", then it should skip the help phase completely.

If the current behavior is intentional, please consider adding a separate flag to fully disable:

- help file classification
- help phase scheduling
- XSD generation

## Environment

- Image: `comol/1c_code_metadata_mcp:light`
- FastMCP: `3.2.4`
- Transport: `streamable-http`
- Updater passes `INDEX_HELP=false` explicitly
