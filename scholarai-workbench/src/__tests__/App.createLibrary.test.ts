import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

describe('App create library input', () => {
  it('opens with an editable blank library id instead of resetting to a fixed name', () => {
    const source = readFileSync(resolve(__dirname, '../App.tsx'), 'utf8');

    expect(source).not.toContain("setNewLibraryId('new_library')");
    expect(source).toContain("setNewLibraryId('')");
    expect(source).toContain('onChange={(e) => setNewLibraryId(e.target.value)}');
  });
});
