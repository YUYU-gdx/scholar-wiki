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
});
