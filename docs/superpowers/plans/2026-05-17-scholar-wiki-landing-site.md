# Scholar Wiki Landing Site Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a static Scholar Wiki product website that explains the product workflow and provides desktop download calls to action.

**Architecture:** Replace the public React entry with a static landing page component that makes no backend API calls. Keep existing workbench modules in the repository, but do not expose a public web-workbench route. Verify the page through source-level unit tests plus a Vite production build.

**Tech Stack:** React 19, TypeScript, Vite, Tailwind CSS, lucide-react, Vitest.

---

## File Structure

- Create `scholarai-workbench/src/components/LandingPage.tsx`: all landing page content, CTA constants, static product visual, and sections.
- Modify `scholarai-workbench/src/App.tsx`: render `LandingPage` as the default public website.
- Create `scholarai-workbench/src/__tests__/LandingPage.static.test.tsx`: source-level tests that ensure no API-backed workbench is mounted and landing content/CTA constants exist.
- Modify `scholarai-workbench/src/index.css`: add small static-site utilities only if the landing page needs them.

## Task 1: Landing Page Contract Test

**Files:**
- Create: `scholarai-workbench/src/__tests__/LandingPage.static.test.tsx`
- Modify: none

- [ ] **Step 1: Write the failing test**

```ts
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

describe('Scholar Wiki landing page static contract', () => {
  const appSource = () => readFileSync(resolve(__dirname, '../App.tsx'), 'utf8');
  const landingSource = () => readFileSync(resolve(__dirname, '../components/LandingPage.tsx'), 'utf8');

  it('uses the landing page as the public app entry without mounting workbench views', () => {
    const source = appSource();

    expect(source).toContain("import LandingPage from './components/LandingPage'");
    expect(source).toContain('return <LandingPage />');
    expect(source).not.toContain('api.');
    expect(source).not.toContain('<LibraryView');
    expect(source).not.toContain('<GraphView');
    expect(source).not.toContain('<ChatView');
  });

  it('defines static desktop download and documentation CTAs in one place', () => {
    const source = landingSource();

    expect(source).toContain("const DOWNLOAD_URL = '#download'");
    expect(source).toContain("const DOCS_URL = '../README.md'");
    expect(source).toContain('Download Desktop App');
    expect(source).toContain('Explore Features');
  });

  it('covers the required product story sections', () => {
    const source = landingSource();

    for (const text of [
      'Import papers',
      'Parse full text',
      'Extract research relationships',
      'Explore and ask',
      'Literature Library',
      'Pipeline',
      'Knowledge Graph',
      'AI Q&A',
      'Reader',
      'Evidence you can inspect',
      'Built for research teams',
      'Static-site ready',
    ]) {
      expect(source).toContain(text);
    }
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- LandingPage.static.test.tsx` from `scholarai-workbench`.

Expected: FAIL because `LandingPage.tsx` does not exist and `App.tsx` still mounts the workbench.

## Task 2: Static Landing Page Implementation

**Files:**
- Create: `scholarai-workbench/src/components/LandingPage.tsx`
- Modify: `scholarai-workbench/src/App.tsx`
- Test: `scholarai-workbench/src/__tests__/LandingPage.static.test.tsx`

- [ ] **Step 1: Create `LandingPage.tsx`**

Implement a single static React component with:

- Header with brand, section anchors, and download CTA.
- Hero with product name, value proposition, static product visual, and CTA buttons.
- Workflow section with four steps.
- Core feature section with five feature modules.
- Trust workflow section.
- Team/lab value section.
- Technology summary with Alibaba/static-site readiness messaging.
- Final `#download` CTA.

Use lucide-react icons and Tailwind classes. Do not import `api`, app context, or workbench views.

- [ ] **Step 2: Replace `App.tsx` entry**

Replace the existing `App.tsx` contents with:

```tsx
import LandingPage from './components/LandingPage';

export default function App() {
  return <LandingPage />;
}
```

- [ ] **Step 3: Run test to verify it passes**

Run: `npm test -- LandingPage.static.test.tsx` from `scholarai-workbench`.

Expected: PASS.

## Task 3: Production Build And Static Output Verification

**Files:**
- Modify: none unless build reveals a specific issue.
- Test: Vite production output.

- [ ] **Step 1: Run TypeScript/build verification**

Run: `npm run build` from `scholarai-workbench`.

Expected: exit 0 and Vite emits `dist/index.html` plus assets.

- [ ] **Step 2: Verify no obvious backend/API dependency in generated entry**

Run: `rg -n "/graph/|/chat/|/literature/|/v1/jobs|EventSource|desktopShell" dist` from `scholarai-workbench`.

Expected: no matches. If matches appear only in sourcemaps from retained chunks, inspect whether `App.tsx` still imports workbench code. The production site must not require backend routes to render.

- [ ] **Step 3: Start a static preview server**

Run: `npm run preview -- --host 0.0.0.0` from `scholarai-workbench`.

Expected: Vite prints a local preview URL. Leave the server running for user review.

## Self-Review

- Spec coverage: the plan includes static landing page, no backend calls, feature sections, trust/team messaging, technical summary, and Alibaba/static deployment readiness.
- Placeholder scan: no TBD/TODO/fill-later steps are present.
- Type consistency: `LandingPage` is a default React component imported by `App.tsx`; tests reference exact paths and strings.
