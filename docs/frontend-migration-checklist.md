# Frontend Migration Checklist

## Goal

Establish a single frontend source of truth and safely retire legacy frontend paths.

## Source of Truth

- Active frontend source: `scholarai-workbench/src`
- Build output (non-source): `scholarai-workbench/dist`
- Legacy path (frozen): `frontend/` (if present)

## Step 1: Freeze legacy frontend

- Do not create/modify files under `frontend/`.
- Keep all frontend feature work in `scholarai-workbench/src`.

## Step 2: Keep build artifacts out of source maintenance

- `scholarai-workbench/dist` is ignored in git.
- Rebuild locally when needed:

```bash
cd scholarai-workbench
npm run build
```

## Step 3: Safe removal checklist for `frontend/`

Run these checks first:

1. Search references in project docs/config/scripts:
```bash
# PowerShell
Get-ChildItem README.md,AGENTS.md,CLAUDE.md,pyproject.toml,docs,scripts,src,tests,scholarai-workbench -Recurse -File |
  Select-String -Pattern 'frontend/|frontend\\'
```

2. Confirm CI/build scripts do not depend on `frontend/`.
3. Confirm no runtime launcher references `frontend/`.

If all clear, remove legacy directory:

```bash
# PowerShell
Remove-Item -Recurse -Force frontend
```

Then run validation:

```bash
cd scholarai-workbench
npm run build
```

## Decision record

- Single frontend codebase policy is now: `scholarai-workbench/src` only.
