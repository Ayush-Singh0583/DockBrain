import { extensionOf, formatBytes } from './format';

/** Matches what the backend's loader accepts (rag/loader.py). */
export const DOCUMENT_EXTENSIONS = ['.pdf', '.docx', '.txt', '.md', '.markdown'];
export const DOCUMENT_ACCEPT = DOCUMENT_EXTENSIONS.join(',');
/** Proposed default; a live backend reports its own limit through capabilities. */
export const DEFAULT_MAX_DOCUMENT_BYTES = 50 * 1024 * 1024;

const TYPE_NAMES = 'a PDF, Word (.docx), text (.txt) or Markdown (.md) file';

export type DocumentValidation =
  | { ok: true; file: File; warning?: string }
  | { ok: false; error: string };

export interface DocumentRules {
  maxBytes?: number;
  extensions?: string[];
}

export function validateDocument(file: File, rules: DocumentRules = {}): DocumentValidation {
  const maxBytes = rules.maxBytes ?? DEFAULT_MAX_DOCUMENT_BYTES;
  const extensions = rules.extensions ?? DOCUMENT_EXTENSIONS;
  const ext = extensionOf(file.name);

  if (ext === '.doc') {
    return {
      ok: false,
      error: `“${file.name}” uses the older Word format. Save it as .docx in Word or LibreOffice, then choose it again.`,
    };
  }
  if (!extensions.includes(ext)) {
    return {
      ok: false,
      error: `“${file.name}” isn’t a supported type. Choose ${TYPE_NAMES}.`,
    };
  }
  if (file.size === 0) {
    return { ok: false, error: `“${file.name}” is empty. Choose a file that contains text.` };
  }
  if (file.size > maxBytes) {
    return {
      ok: false,
      error: `“${file.name}” is ${formatBytes(file.size)}, over the ${formatBytes(maxBytes)} limit. Choose a smaller file or split it into parts.`,
    };
  }
  return { ok: true, file };
}

/** Validates a picker or drop result. DockBrain reads one document at a time. */
export function validateDocumentList(files: File[], rules: DocumentRules = {}): DocumentValidation {
  if (files.length === 0) {
    return { ok: false, error: `Nothing was selected. Choose ${TYPE_NAMES}.` };
  }
  const first = files[0]!;
  const result = validateDocument(first, rules);
  if (result.ok && files.length > 1) {
    return { ...result, warning: `DockBrain reads one document at a time, so it kept “${first.name}”.` };
  }
  return result;
}

export const FOLDER_IN_DOCUMENT_FLOW =
  'That’s a folder. To explore a project folder, go back and choose “Understand a codebase”.';
