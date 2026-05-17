import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

describe('DocumentResolver', () => {
  const mockShell = {
    platform: 'win32',
    runtime: 'electron',
    resolvePaperPaths: vi.fn(),
    readLocalText: vi.fn(),
    readLocalFile: vi.fn(),
  };

  beforeEach(() => {
    vi.resetAllMocks();
    // @ts-expect-error -- mock shell is incomplete by design
    window.desktopShell = mockShell;
  });

  afterEach(() => {
    delete window.desktopShell;
  });

  it('fetches file paths and reads a markdown file', async () => {
    mockShell.resolvePaperPaths.mockResolvedValueOnce({
      ok: true,
      files: {
        markdown: { path: '/data/test.md', name: 'test.md', size_bytes: 64 },
      },
    });
    mockShell.readLocalText.mockResolvedValueOnce({
      ok: true,
      data: '# Hello',
    });

    const { resolveAndLoadDocument } = await import('../../components/reader/DocumentResolver');
    const result = await resolveAndLoadDocument('doi_test', 'supply_chain');
    expect(result.type).toBe('markdown');
    expect(result.data).toBe('# Hello');
    expect(result.file_name).toBe('test.md');
    expect(mockShell.resolvePaperPaths).toHaveBeenCalledWith('doi_test', 'supply_chain');
  });

  it('returns none when no files available', async () => {
    mockShell.resolvePaperPaths.mockResolvedValueOnce({
      ok: true,
      files: {},
    });

    const { resolveAndLoadDocument } = await import('../../components/reader/DocumentResolver');
    const result = await resolveAndLoadDocument('doi_test', 'supply_chain');
    expect(result.type).toBe('none');
    expect(result.data).toBeNull();
  });

  it('falls back to rawPaperId when primary id returns not ok', async () => {
    mockShell.resolvePaperPaths
      .mockResolvedValueOnce({ ok: false, status: 404 })
      .mockResolvedValueOnce({
        ok: true,
        files: {
          markdown: { path: '/data/raw.md', name: 'raw.md', size_bytes: 64 },
        },
      });
    mockShell.readLocalText.mockResolvedValueOnce({
      ok: true,
      data: '# Fallback',
    });

    const { resolveAndLoadDocument } = await import('../../components/reader/DocumentResolver');
    const result = await resolveAndLoadDocument('paper_404', 'supply_chain', 'raw_ok');
    expect(result.type).toBe('markdown');
    expect(result.data).toBe('# Fallback');
    expect(mockShell.resolvePaperPaths).toHaveBeenCalledTimes(2);
    expect(mockShell.resolvePaperPaths).toHaveBeenLastCalledWith('raw_ok', 'supply_chain');
  });

  it('loads a direct markdown path without resolving paper paths', async () => {
    mockShell.readLocalText.mockResolvedValueOnce({
      ok: true,
      data: '# Direct file',
    });

    const { resolveAndLoadDocument } = await import('../../components/reader/DocumentResolver');
    const doc = await resolveAndLoadDocument('file:C:\\papers\\Direct.md', 'supply_chain', undefined, 'markdown', 'C:\\papers\\Direct.md');

    expect(mockShell.resolvePaperPaths).not.toHaveBeenCalled();
    expect(mockShell.readLocalText).toHaveBeenCalledWith('C:\\papers\\Direct.md');
    expect(doc).toMatchObject({
      type: 'markdown',
      data: '# Direct file',
      file_name: 'Direct.md',
      absolute_path: 'C:\\papers\\Direct.md',
      markdown_path: 'C:\\papers\\Direct.md',
    });
  });

  it('returns none when all resolve attempts fail', async () => {
    mockShell.resolvePaperPaths
      .mockResolvedValueOnce({ ok: false, status: 500 })
      .mockResolvedValueOnce({ ok: false, status: 404 });

    const { resolveAndLoadDocument } = await import('../../components/reader/DocumentResolver');
    const result = await resolveAndLoadDocument('paper_500', 'supply_chain', 'raw_ok');
    expect(result.type).toBe('none');
    expect(mockShell.resolvePaperPaths).toHaveBeenCalledTimes(2);
  });

  it('throws when not in electron runtime', async () => {
    delete window.desktopShell;

    const { resolveAndLoadDocument } = await import('../../components/reader/DocumentResolver');
    await expect(resolveAndLoadDocument('doi_test', 'supply_chain')).rejects.toThrow('reader_requires_electron_runtime');
  });
});
