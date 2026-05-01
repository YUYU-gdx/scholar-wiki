export interface AnnotationRect {
  x: number;
  y: number;
  width: number;
  height: number;
  page_index: number;
}

export interface InkPath {
  points: { x: number; y: number }[];
  width: number;
  color: string;
}

export type AnnotationType = 'highlight' | 'underline' | 'note' | 'ink';

export interface Annotation {
  id: string;
  paper_id: string;
  library_id: string;
  type: AnnotationType;
  page_index: number;
  rects: AnnotationRect[];
  text: string;
  comment: string;
  color: string;
  ink_paths: InkPath[];
  linked_node_ids: string[];
  created_at: string;
  updated_at: string;
}

export interface AnnotationCreate {
  paper_id: string;
  library_id: string;
  type: AnnotationType;
  page_index: number;
  rects: AnnotationRect[];
  text: string;
  comment: string;
  color: string;
  ink_paths: InkPath[];
  linked_node_ids: string[];
}

export type ViewerMode = 'edit' | 'live-preview' | 'read';

export { type PaperFilesFileInfo, type PaperFiles } from '../../types';

export interface DocumentLoadResult {
  type: 'pdf' | 'markdown' | 'html' | 'none';
  data: Uint8Array | string | null;
  file_name: string;
}
