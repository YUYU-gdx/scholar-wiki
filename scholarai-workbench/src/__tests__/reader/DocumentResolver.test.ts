import { describe, it, expect, vi, beforeEach } from 'vitest';

const mockFetch = vi.fn();
global.fetch = mockFetch as unknown as typeof fetch;

describe('DocumentResolver', () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it('resolves paper_id to file list via API', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({
        paper_id: 'doi_test',
        library_id: 'supply_chain',
        files: {
          pdf: { path: '/data/test.pdf', name: 'test.pdf', size_bytes: 1000 },
        },
        default_view: 'pdf',
      }),
    });

    const { resolvePaperFiles } = await import('../../components/reader/DocumentResolver');
    const result = await resolvePaperFiles('doi_test', 'supply_chain');
    expect(result.default_view).toBe('pdf');
    expect(result.files.pdf).toBeDefined();
    expect(result.files.pdf!.name).toBe('test.pdf');
  });

  it('returns none when no files available', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({
        paper_id: 'doi_test',
        library_id: 'supply_chain',
        files: {},
        default_view: 'none',
      }),
    });

    const { resolvePaperFiles } = await import('../../components/reader/DocumentResolver');
    const result = await resolvePaperFiles('doi_test', 'supply_chain');
    expect(result.default_view).toBe('none');
    expect(Object.keys(result.files)).toHaveLength(0);
  });

  it('falls back to rawPaperId when primary paper id returns 404', async () => {
    mockFetch
      .mockResolvedValueOnce({
        ok: false,
        status: 404,
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: () => Promise.resolve({
          paper_id: 'raw_ok',
          library_id: 'supply_chain',
          files: {
            markdown: { path: '/data/raw.md', name: 'raw.md', size_bytes: 64 },
          },
          default_view: 'markdown',
        }),
      });

    const { resolvePaperFiles } = await import('../../components/reader/DocumentResolver');
    const result = await resolvePaperFiles('paper_404', 'supply_chain', 'raw_ok');
    expect(result.default_view).toBe('markdown');
    expect(result.paper_id).toBe('raw_ok');
    expect(mockFetch).toHaveBeenCalledTimes(2);
  });

  it('does not fall back to rawPaperId when primary paper id returns 500', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 500,
    });

    const { resolvePaperFiles } = await import('../../components/reader/DocumentResolver');
    await expect(resolvePaperFiles('paper_500', 'supply_chain', 'raw_ok')).rejects.toThrow('failed to resolve paper files: 500');
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });
});
