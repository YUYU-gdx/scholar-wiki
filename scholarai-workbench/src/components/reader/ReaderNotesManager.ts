import { openDB, type IDBPDatabase } from 'idb';

export interface ReaderNoteRecord {
  id: string;
  paper_id: string;
  library_id: string;
  doc_type: 'pdf' | 'markdown';
  page_index: number;
  selected_text: string;
  note_text: string;
  md_anchor: {
    quote: string;
    prefix: string;
    suffix: string;
    hash: string;
  };
  markdown_path_at_write?: string;
  created_at: string;
  updated_at: string;
}

const DB_NAME = 'kn-graph-reader';
const STORE = 'reader_notes';
const VERSION = 2;
let dbPromise: Promise<IDBPDatabase> | null = null;

function hashText(input: string): string {
  let h = 2166136261;
  const s = String(input || '').toLowerCase().replace(/\s+/g, ' ').trim();
  for (let i = 0; i < s.length; i += 1) {
    h ^= s.charCodeAt(i);
    h += (h << 1) + (h << 4) + (h << 7) + (h << 8) + (h << 24);
  }
  return (h >>> 0).toString(16);
}

function getDb(): Promise<IDBPDatabase> {
  if (!dbPromise) {
    dbPromise = openDB(DB_NAME, VERSION, {
      upgrade(db) {
        if (!db.objectStoreNames.contains(STORE)) {
          const store = db.createObjectStore(STORE, { keyPath: 'id' });
          store.createIndex('paper_id', 'paper_id', { unique: false });
          store.createIndex('created_at', 'created_at', { unique: false });
        }
      },
    });
  }
  return dbPromise;
}

export const readerNotesManager = {
  makeAnchor(fullText: string, selectedText: string): ReaderNoteRecord['md_anchor'] {
    const doc = String(fullText || '');
    const quote = String(selectedText || '').trim();
    const idx = doc.indexOf(quote);
    const prefix = idx >= 0 ? doc.slice(Math.max(0, idx - 80), idx) : '';
    const suffix = idx >= 0 ? doc.slice(idx + quote.length, idx + quote.length + 80) : '';
    return { quote, prefix, suffix, hash: hashText(quote) };
  },
  async add(input: Omit<ReaderNoteRecord, 'id' | 'created_at' | 'updated_at'> & { id?: string }): Promise<ReaderNoteRecord> {
    const db = await getDb();
    const now = new Date().toISOString();
    const row: ReaderNoteRecord = {
      ...input,
      id: String(input.id || crypto.randomUUID()),
      created_at: now,
      updated_at: now,
    };
    await db.put(STORE, row);
    return row;
  },
  async listByPaper(paperId: string): Promise<ReaderNoteRecord[]> {
    const db = await getDb();
    const index = db.transaction(STORE).store.index('paper_id');
    return index.getAll(paperId);
  },
  async update(id: string, noteText: string): Promise<void> {
    const db = await getDb();
    const tx = db.transaction(STORE, 'readwrite');
    const store = tx.objectStore(STORE);
    const row = await store.get(id) as ReaderNoteRecord | undefined;
    if (!row) return;
    row.note_text = String(noteText || '').trim();
    row.updated_at = new Date().toISOString();
    await store.put(row);
    await tx.done;
  },
  async setMarkdownPath(id: string, markdownPath: string): Promise<void> {
    const db = await getDb();
    const tx = db.transaction(STORE, 'readwrite');
    const store = tx.objectStore(STORE);
    const row = await store.get(id) as ReaderNoteRecord | undefined;
    if (!row) return;
    row.markdown_path_at_write = String(markdownPath || '').trim();
    row.updated_at = new Date().toISOString();
    await store.put(row);
    await tx.done;
  },
  async remove(id: string): Promise<void> {
    const db = await getDb();
    await db.delete(STORE, id);
  },
};
