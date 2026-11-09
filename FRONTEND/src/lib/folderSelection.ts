/**
 * Real, local codebase-folder handling: collecting files from a folder picker or a drop,
 * skipping dependency/build folders, and summarising languages from file names and sizes.
 * No file contents are read here.
 */
import type { CodeFile } from '../services/types';
import { extensionOf } from './format';

export const IGNORED_DIRECTORIES = new Set([
  '.git', '.hg', '.svn', 'node_modules', 'bower_components', '.venv', 'venv', 'env',
  '__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache', '.tox', 'dist', 'build',
  'out', 'target', '.next', '.nuxt', '.cache', '.parcel-cache', 'coverage', '.idea',
  '.vscode', '.gradle', 'Pods', 'vendor',
]);

export const MAX_CODEBASE_FILES = 5000;
export const MAX_CODEBASE_BYTES = 200 * 1024 * 1024;

const LANGUAGES: Record<string, string> = {
  '.py': 'Python', '.ts': 'TypeScript', '.tsx': 'TypeScript', '.js': 'JavaScript',
  '.jsx': 'JavaScript', '.mjs': 'JavaScript', '.cjs': 'JavaScript', '.java': 'Java',
  '.kt': 'Kotlin', '.go': 'Go', '.rs': 'Rust', '.rb': 'Ruby', '.php': 'PHP', '.cs': 'C#',
  '.c': 'C', '.h': 'C', '.cpp': 'C++', '.cc': 'C++', '.hpp': 'C++', '.swift': 'Swift',
  '.m': 'Objective-C', '.scala': 'Scala', '.dart': 'Dart', '.lua': 'Lua', '.r': 'R',
  '.sh': 'Shell', '.bash': 'Shell', '.ps1': 'PowerShell', '.sql': 'SQL', '.html': 'HTML',
  '.css': 'CSS', '.scss': 'CSS', '.vue': 'Vue', '.svelte': 'Svelte', '.md': 'Markdown',
  '.json': 'JSON', '.yml': 'YAML', '.yaml': 'YAML', '.toml': 'TOML', '.ipynb': 'Jupyter',
};

export interface LanguageShare {
  name: string;
  files: number;
  bytes: number;
  /** Share of the bytes of recognised source files, 0–1. */
  share: number;
}

export interface CodebaseSelection {
  name: string;
  files: CodeFile[];
  totalBytes: number;
  /** Files skipped because they sit in dependency or build folders. */
  ignoredCount: number;
  /** True when the folder had more files than DockBrain accepts and the rest were left out. */
  truncated: boolean;
  languages: LanguageShare[];
  /** False when the browser could only select individual files, so there are no real paths. */
  fromFolder: boolean;
}

export type CodebaseValidation =
  | { ok: true; selection: CodebaseSelection; warning?: string }
  | { ok: false; error: string };

export interface RawEntry {
  /** Path including the top folder name, "/"-separated, e.g. "myproj/src/app.py". */
  path: string;
  file: File;
}

export function isIgnoredPath(path: string): boolean {
  return path.split('/').slice(0, -1).some((part) => IGNORED_DIRECTORIES.has(part));
}

export function supportsFolderPicker(): boolean {
  return typeof HTMLInputElement !== 'undefined' && 'webkitdirectory' in HTMLInputElement.prototype;
}

/** Entries from an `<input webkitdirectory>` (or a plain multi-file fallback). */
export function entriesFromInput(files: File[]): { entries: RawEntry[]; fromFolder: boolean } {
  const fromFolder = files.some((f) => f.webkitRelativePath);
  return {
    fromFolder,
    entries: files.map((file) => ({ path: file.webkitRelativePath || file.name, file })),
  };
}

export function summariseLanguages(files: CodeFile[]): LanguageShare[] {
  const byName = new Map<string, { files: number; bytes: number }>();
  for (const f of files) {
    const name = LANGUAGES[extensionOf(f.path)];
    if (!name) continue;
    const entry = byName.get(name) ?? { files: 0, bytes: 0 };
    entry.files += 1;
    entry.bytes += f.size;
    byName.set(name, entry);
  }
  const total = [...byName.values()].reduce((sum, e) => sum + e.bytes, 0);
  return [...byName.entries()]
    .map(([name, e]) => ({ name, ...e, share: total ? e.bytes / total : 0 }))
    .sort((a, b) => b.bytes - a.bytes || b.files - a.files);
}

export function buildCodebaseSelection(
  entries: RawEntry[],
  options: { fromFolder: boolean; ignoredCount?: number; truncated?: boolean },
): CodebaseValidation {
  if (entries.length === 0) {
    return {
      ok: false,
      error: options.ignoredCount
        ? 'Every file in that folder is in a dependency or build folder (like node_modules). Choose the project’s source folder.'
        : 'That folder looks empty. Choose a folder that contains the project’s files.',
    };
  }

  const firstSegments = new Set(entries.map((e) => (e.path.includes('/') ? e.path.split('/')[0] : '')));
  const sharedRoot = firstSegments.size === 1 ? [...firstSegments][0]! : '';
  const name = options.fromFolder && sharedRoot ? sharedRoot : 'Selected files';

  let ignoredCount = options.ignoredCount ?? 0;
  let truncated = options.truncated ?? false;
  const files: CodeFile[] = [];
  let totalBytes = 0;

  for (const entry of entries) {
    const path = sharedRoot ? entry.path.slice(sharedRoot.length + 1) : entry.path;
    if (isIgnoredPath(path)) {
      ignoredCount += 1;
      continue;
    }
    if (files.length >= MAX_CODEBASE_FILES || totalBytes + entry.file.size > MAX_CODEBASE_BYTES) {
      truncated = true;
      continue;
    }
    files.push({ path, size: entry.file.size, file: entry.file });
    totalBytes += entry.file.size;
  }

  if (files.length === 0) {
    return buildCodebaseSelection([], { fromFolder: options.fromFolder, ignoredCount });
  }

  files.sort((a, b) => a.path.localeCompare(b.path));
  const selection: CodebaseSelection = {
    name,
    files,
    totalBytes,
    ignoredCount,
    truncated,
    languages: summariseLanguages(files),
    fromFolder: options.fromFolder,
  };
  return {
    ok: true,
    selection,
    warning: truncated
      ? `This folder is large, so DockBrain kept the first ${files.length.toLocaleString()} files. Choose a subfolder to include everything.`
      : undefined,
  };
}

/* ------------------------------------------------------ drag-and-drop folders */

function readAllEntries(reader: FileSystemDirectoryReader): Promise<FileSystemEntry[]> {
  return new Promise((resolve, reject) => {
    const all: FileSystemEntry[] = [];
    const next = () =>
      reader.readEntries((batch) => {
        if (batch.length === 0) resolve(all);
        else {
          all.push(...batch);
          next();
        }
      }, reject);
    next();
  });
}

function entryFile(entry: FileSystemFileEntry): Promise<File> {
  return new Promise((resolve, reject) => entry.file(resolve, reject));
}

export interface DroppedItems {
  entries: RawEntry[];
  /** Whether any dropped item was a directory. */
  hasDirectory: boolean;
  ignoredCount: number;
  truncated: boolean;
}

/**
 * Reads files from a drop, walking into folders and skipping ignored ones without
 * descending into them. Call synchronously from the drop handler: the browser
 * invalidates `dataTransfer.items` once the handler returns, so entries are taken first.
 */
export function readDroppedItems(dataTransfer: DataTransfer): Promise<DroppedItems> {
  const rootEntries: FileSystemEntry[] = [];
  const looseFiles: File[] = [];
  for (const item of Array.from(dataTransfer.items ?? [])) {
    if (item.kind !== 'file') continue;
    const entry = typeof item.webkitGetAsEntry === 'function' ? item.webkitGetAsEntry() : null;
    if (entry) rootEntries.push(entry);
    else {
      const file = item.getAsFile();
      if (file) looseFiles.push(file);
    }
  }
  if (rootEntries.length === 0 && looseFiles.length === 0) {
    looseFiles.push(...Array.from(dataTransfer.files ?? []));
  }

  return (async () => {
    const result: DroppedItems = {
      entries: looseFiles.map((file) => ({ path: file.name, file })),
      hasDirectory: false,
      ignoredCount: 0,
      truncated: false,
    };

    const walk = async (entry: FileSystemEntry, prefix: string): Promise<void> => {
      if (result.entries.length >= MAX_CODEBASE_FILES) {
        result.truncated = true;
        return;
      }
      const path = prefix ? `${prefix}/${entry.name}` : entry.name;
      if (entry.isFile) {
        result.entries.push({ path, file: await entryFile(entry as FileSystemFileEntry) });
        return;
      }
      if (!entry.isDirectory) return;
      if (prefix && IGNORED_DIRECTORIES.has(entry.name)) {
        result.ignoredCount += 1; // counted per skipped folder, not per file inside it
        return;
      }
      const children = await readAllEntries((entry as FileSystemDirectoryEntry).createReader());
      for (const child of children) await walk(child, path);
    };

    for (const entry of rootEntries) {
      if (entry.isDirectory) result.hasDirectory = true;
      await walk(entry, '');
    }
    return result;
  })();
}
