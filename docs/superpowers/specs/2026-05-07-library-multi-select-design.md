# LibraryView Multi-Select & Context Menu

## Context

LibraryView currently supports only single-paper selection. Users need multi-select (shift-click, ctrl-click, ctrl+A) and a right-click context menu for batch operations (open PDF/MD, expand/collapse, batch delete). This is a pure frontend interaction change — no backend API changes, no style changes.

## Scope

- Papers list only (not Variables table)
- Single file: `scholarai-workbench/src/components/LibraryView.tsx`
- No new dependencies
- No style changes (reuse existing Tailwind classes)

## Git Safety

Use `git worktree` for isolated development:

```
git worktree add .claude/worktrees/feat-library-multi-select feat/library-multi-select
```

Work in the worktree. Master remains untouched. Cleanup via `git worktree remove` + `git branch -D` if needed.

## Selection State Model

Pure memory state via `useRef` (not `useState`, to avoid re-renders on every Set mutation):

```typescript
type SelectionState = {
  pivot: number;           // shift-click anchor index
  focused: number;         // keyboard focus index
  selected: Set<number>;   // selected indices into paperList
};
```

Visual feedback: add `ring-2 ring-secondary` to selected rows. No new colors, no layout changes.

## Interaction Design

### Mouse Events (on each row)

| Action | Condition | Behavior |
|---|---|---|
| Plain click | `!shiftKey && !ctrlKey && !metaKey` | `select(index)` — clear others, single select |
| Ctrl/Cmd+click | `ctrlKey \|\| metaKey` | `toggleSelect(index)` — flip this row |
| Shift+click | `shiftKey` | `shiftSelect(index)` — select range pivot→index |
| Right-click (in selection) | `selected.has(index)` | Keep multi-select, show menu |
| Right-click (not in selection) | `!selected.has(index)` | `select(index)` first, then show menu |

Button clicks inside rows (PDF/MD/delete/expand) use `e.stopPropagation()` to prevent row selection.

### Keyboard Events (on list container)

| Key | Behavior |
|---|---|
| Ctrl/Cmd+A | Select all paperList indices |
| Escape | Clear selection |

## Context Menu

Native positioned `<div>`, no external library. Controlled by `{x, y, visible}` state.

### Menu Items

| Item | Condition | Action |
|---|---|---|
| Open in Reader (PDF) | At least one selected paper has PDF | Open first selected paper with PDF |
| Open in Reader (MD) | At least one selected paper has MD | Open first selected paper with MD |
| Expand / Collapse | Single: toggle that paper. Multiple: unified expand/collapse all selected | Batch toggle |
| Delete (N papers) | Always visible, red text | `Promise.allSettled` batch delete, then summary alert |

### Dismiss

Click outside, press Escape, or scroll closes the menu.

## Implementation Steps

1. Create `feat/library-multi-select` branch via git worktree
2. Add `SelectionState` type and `useRef` to LibraryView
3. Implement `select`, `toggleSelect`, `shiftSelect` functions
4. Wire up `onClick`, `onContextMenu` on each paper row
5. Add `onKeyDown` handler on the list container for Ctrl+A and Escape
6. Implement context menu div with dynamic menu items
7. Implement batch delete with `Promise.allSettled`
8. Add `e.stopPropagation()` to existing buttons
9. Manual smoke test: single click, ctrl+click, shift+click, ctrl+A, right-click menu, batch delete
10. Commit on feature branch, merge back to master

## Verification

- Single click selects one paper, deselects others
- Ctrl+click toggles individual papers
- Shift+click selects range from first click to current
- Ctrl+A selects all papers
- Right-click unselected row: selects it then shows menu
- Right-click when multiple selected: keeps selection, shows menu
- "Delete (N)" confirms once then deletes all selected
- Escape clears selection
- Existing single-paper operations still work (PDF/MD buttons, expand, delete)
