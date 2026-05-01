# Data Directory Unification Design

**Date**: 2026-04-30
**Status**: Draft

## Problem

Currently, application data is scattered across multiple locations:

| Data | Current Location | Config Mechanism |
|------|-----------------|-----------------|
| Library workspaces | `D:\KNGraphApp\libraries\workspaces` (Win) | Hardcoded default in `library_registry.py` |
| Library registry | `outputs/libraries/registry.json` (repo-relative) | `LITERATURE_LIBRARY_REGISTRY_PATH` env |
| Literature indexes | `outputs/literature_libraries` (repo-relative) | `LITERATURE_LIBRARY_INDEX_ROOT` env |
| Pipeline jobs DB | `jobs.db` (cwd-relative) | `pipeline_job_store_dsn` in Settings |
| Chat store | In-memory (no persistence) | `chat_store_dsn` defaults to empty |
| Workspace layouts | `outputs/workbench/workspace_layouts.json` | Hardcoded in `workspace_service.py` |

Problems:
1. Data lives in the source repo (`outputs/`) — won't survive repo resets
2. Path configuration uses two incompatible env var prefixes (`LITERATURE_*` vs `KN_GRAPH_*`)
3. New `Settings` class lacks data directory fields entirely
4. On Windows, `D:\KNGraphApp` is already the de facto location for workspaces but other data doesn't go there
5. No auto-creation of directory structure on first launch

## Goal

Unify all application data under a single configurable root directory (`data_dir`) with a clear subdirectory structure. Default to `D:\KNGraphApp` on Windows, `~/.kn_graph` on other platforms.

## Target Directory Structure

```
{data_dir}/
├── libraries/
│   ├── registry.json              ← library registry
│   ├── workspaces/                ← per-library workspace dirs
│   │   ├── supply_chain/
│   │   └── lib_a/
│   └── indexes/                   ← literature search indexes
├── pipeline/
│   └── jobs.sqlite                ← pipeline job database
├── chat/
│   └── store.sqlite               ← chat session persistence
└── workbench/
    └── layouts.json               ← UI workspace layouts
```

## Implementation Plan

### 1. Add `data_dir` to `Settings`

**File**: `src/kn_graph/config.py`

Add a `data_dir` field with computed sub-path properties:

```python
def _default_data_dir() -> Path:
    """Windows: D:\\KNGraphApp, others: ~/.kn_graph"""
    if os.name == "nt":
        return Path(r"D:\KNGraphApp")
    return Path.home() / ".kn_graph"

class Settings(BaseSettings):
    # ... existing fields ...

    data_dir: Path = Field(default_factory=_default_data_dir)

    @property
    def libraries_dir(self) -> Path:
        return self.data_dir / "libraries"

    @property
    def workspaces_dir(self) -> Path:
        return self.libraries_dir / "workspaces"

    @property
    def registry_path(self) -> Path:
        return self.libraries_dir / "registry.json"

    @property
    def indexes_dir(self) -> Path:
        return self.libraries_dir / "indexes"

    @property
    def pipeline_db_path(self) -> Path:
        return self.data_dir / "pipeline" / "jobs.sqlite"

    @property
    def chat_store_path(self) -> Path:
        return self.data_dir / "chat" / "store.sqlite"

    @property
    def workspace_layouts_path(self) -> Path:
        return self.data_dir / "workbench" / "layouts.json"
```

Since `data_dir` is a `Path` field with `KN_GRAPH_` env prefix, users can override it via `KN_GRAPH_DATA_DIR`.

**Note on `Path` defaults**: pydantic-settings supports `Path` fields. The conditional default uses `default_factory` since the value depends on `os.name`. The `pipeline_job_store_dsn` and `chat_store_dsn` string fields keep their empty-string defaults but are populated at runtime from `data_dir` if left empty — this avoids circular field references in the model.

Pydantic-settings with `env_prefix = "KN_GRAPH_"` will automatically map `KN_GRAPH_DATA_DIR` env var to `data_dir`.

### 2. Ensure Data Directory on Startup

**File**: `src/kn_graph/app.py`

Call `ensure_data_dirs(settings)` at app creation time:

```python
def ensure_data_dirs(settings: Settings) -> None:
    dirs = [
        settings.data_dir,
        settings.libraries_dir,
        settings.workspaces_dir,
        settings.indexes_dir,
        settings.data_dir / "pipeline",
        settings.data_dir / "chat",
        settings.data_dir / "workbench",
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
```

### 3. Update Services to Use Settings Paths

#### `literature_service.py`

- Replace hardcoded `Path("outputs/literature_libraries")` with `settings.indexes_dir`
- Pass `settings.registry_path` to the legacy `LiteratureService`

#### `chat_service.py`

- If `chat_store_dsn` is empty, compute it from `settings.chat_store_path` as `f"sqlite:///{settings.chat_store_path}"`
- Use `settings.workspaces_dir` for workspace resolution

#### `pipeline_service.py`

- If `pipeline_job_store_dsn` equals the old default `"sqlite:///jobs.db"`, override it with `f"sqlite:///{settings.pipeline_db_path}"`

#### `workspace_service.py`

- Replace hardcoded `Path("outputs/workbench/workspace_layouts.json")` with `settings.workspace_layouts_path`

### 4. Update `library_registry.py` to Accept External Paths

The legacy `library_registry.py` currently reads `LITERATURE_*` env vars directly. We need to:

- Add a `configure(registry_path, workspaces_root, index_root)` function that can be called from the new code
- In `src/kn_graph/services/literature_service.py`, call this configuration at startup with values from `Settings`
- Keep backward compatibility: if `LITERATURE_*` env vars are set, they still take precedence

### 5. Migrate Existing Data on First Launch

**File**: `src/kn_graph/app.py` (or a separate `src/kn_graph/migration.py`)

On first launch (detected by `registry.json` not existing in new location):

1. Check old location `outputs/libraries/registry.json` — if exists, copy to `{data_dir}/libraries/registry.json`
2. Check old location `outputs/literature_libraries/` — if exists, copy to `{data_dir}/libraries/indexes/`
3. Check old location `jobs.db` — if exists, copy to `{data_dir}/pipeline/jobs.sqlite`
4. Check old location `outputs/workbench/workspace_layouts.json` — if exists, copy to `{data_dir}/workbench/layouts.json`
5. Workspaces are already at `D:\KNGraphApp\libraries\workspaces` — update `registry.json` path references

Migration is copy-only; old data is never deleted automatically. A one-time log message says where data was migrated from.

### 6. Update Electron Launcher

**File**: `scholarai-workbench/electron/main.cjs`

- Add `--data-dir` argument to the backend spawn command, pointing to `D:\KNGraphApp`
- Alternatively, set `KN_GRAPH_DATA_DIR` environment variable in `buildPythonEnv()`

### 7. Frontend — No Changes Needed

The frontend talks to the backend via API endpoints. All path configuration is server-side. No frontend code changes required for this feature.

## Environment Variable Compatibility

| Old Env Var | New Equiv (via Settings) | Behavior |
|---|---|---|
| `LITERATURE_LIBRARY_WORKSPACES_ROOT` | `KN_GRAPH_DATA_DIR` → `workspaces_dir` | Old env still works for backward compat |
| `LITERATURE_LIBRARY_REGISTRY_PATH` | `KN_GRAPH_DATA_DIR` → `registry_path` | Old env still works |
| `LITERATURE_LIBRARY_INDEX_ROOT` | `KN_GRAPH_DATA_DIR` → `indexes_dir` | Old env still works |
| — | `KN_GRAPH_DATA_DIR` | New unified control; overrides all `LITERATURE_*` paths when set |

Priority: explicit `LITERATURE_*` env vars > `KN_GRAPH_DATA_DIR` derived paths > hardcoded defaults.

## Testing

1. Launch with no existing data → directories auto-created
2. Launch with existing `D:\KNGraphApp\libraries\workspaces` → workspaces discovered
3. Launch with old `outputs/` data → migration copies to new locations
4. Set `KN_GRAPH_DATA_DIR=/custom/path` → all data goes to custom path
5. Set `LITERATURE_LIBRARY_WORKSPACES_ROOT=/custom/ws` → overrides only workspaces, rest from `KN_GRAPH_DATA_DIR`

## Scope

This change covers backend path unification only. The Electron shell's `--data-dir` forwarding is included. No frontend data directory changes needed.