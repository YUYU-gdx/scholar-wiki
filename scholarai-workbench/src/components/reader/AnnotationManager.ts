import { openDB, type IDBPDatabase } from 'idb';
import type { Annotation, AnnotationCreate } from './types';

const DB_NAME = 'kn-graph-reader';
const STORE_NAME = 'annotations';
const DB_VERSION = 1;

let dbPromise: Promise<IDBPDatabase> | null = null;

function getDb(): Promise<IDBPDatabase> {
  if (!dbPromise) {
    dbPromise = openDB(DB_NAME, DB_VERSION, {
      upgrade(db) {
        if (!db.objectStoreNames.contains(STORE_NAME)) {
          const store = db.createObjectStore(STORE_NAME, { keyPath: 'id' });
          store.createIndex('paper_id', 'paper_id', { unique: false });
          store.createIndex('page_index', 'page_index', { unique: false });
          store.createIndex('created_at', 'created_at', { unique: false });
        }
      },
    });
  }
  return dbPromise;
}

export const annotationManager = {
  async getAllByPaper(paperId: string): Promise<Annotation[]> {
    const db = await getDb();
    const index = db.transaction(STORE_NAME).store.index('paper_id');
    return index.getAll(paperId);
  },

  async add(create: AnnotationCreate): Promise<Annotation> {
    const db = await getDb();
    const now = new Date().toISOString();
    const annotation: Annotation = {
      ...create,
      id: crypto.randomUUID(),
      created_at: now,
      updated_at: now,
    };
    await db.add(STORE_NAME, annotation);
    return annotation;
  },

  async update(id: string, changes: Partial<Pick<Annotation, 'comment' | 'color' | 'linked_node_ids'>>): Promise<void> {
    const db = await getDb();
    const tx = db.transaction(STORE_NAME, 'readwrite');
    const store = tx.objectStore(STORE_NAME);
    const existing = await store.get(id);
    if (!existing) return;
    const updated = { ...existing, ...changes, updated_at: new Date().toISOString() };
    await store.put(updated);
    await tx.done;
  },

  async remove(id: string): Promise<void> {
    const db = await getDb();
    await db.delete(STORE_NAME, id);
  },

  async removeByPaper(paperId: string): Promise<void> {
    const db = await getDb();
    const tx = db.transaction(STORE_NAME, 'readwrite');
    const index = tx.store.index('paper_id');
    const all = await index.getAllKeys(paperId);
    for (const key of all) {
      await tx.store.delete(key);
    }
    await tx.done;
  },

  async exportByPaper(paperId: string): Promise<Annotation[]> {
    return this.getAllByPaper(paperId);
  },
};
