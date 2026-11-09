import { describe, expect, it } from 'vitest';
import { validateDocument, validateDocumentList } from './fileValidation';
import { buildCodebaseSelection, entriesFromInput, isIgnoredPath, summariseLanguages } from './folderSelection';
import { attachCitations, splitCitations } from './citations';
import { formatBytes } from './format';

const file = (name: string, size = 10, type = '') => new File([new Uint8Array(size)], name, { type });

describe('validateDocument', () => {
  it.each(['report.pdf', 'Report.PDF', 'notes.docx', 'a.txt', 'readme.md', 'guide.markdown'])('accepts %s', (name) => {
    expect(validateDocument(file(name)).ok).toBe(true);
  });

  it('explains the old Word format instead of a generic rejection', () => {
    const result = validateDocument(file('thesis.doc'));
    expect(result).toEqual({ ok: false, error: expect.stringContaining('Save it as .docx') });
  });

  it('rejects unsupported types, naming the supported ones', () => {
    const result = validateDocument(file('photo.png'));
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error).toMatch(/“photo.png” isn’t a supported type.*PDF/);
  });

  it('rejects empty files and files over the limit', () => {
    expect(validateDocument(file('empty.txt', 0))).toMatchObject({ ok: false, error: expect.stringContaining('is empty') });
    const big = validateDocument(file('big.pdf', 2048), { maxBytes: 1024 });
    expect(big).toMatchObject({ ok: false, error: expect.stringContaining('over the 1 KB limit') });
  });

  it('keeps the first of several files and says so', () => {
    const result = validateDocumentList([file('a.pdf'), file('b.pdf')]);
    expect(result).toMatchObject({ ok: true, warning: expect.stringContaining('kept “a.pdf”') });
    expect(validateDocumentList([]).ok).toBe(false);
  });
});

describe('codebase folders', () => {
  const entry = (path: string, size = 100) => ({ path, file: file(path.split('/').pop()!, size) });

  it('skips dependency and build folders and strips the shared folder name', () => {
    const result = buildCodebaseSelection(
      [entry('proj/src/app.py', 300), entry('proj/node_modules/x/index.js'), entry('proj/.git/HEAD'), entry('proj/README.md', 50)],
      { fromFolder: true },
    );
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.selection.name).toBe('proj');
    expect(result.selection.files.map((f) => f.path)).toEqual(['README.md', 'src/app.py']);
    expect(result.selection.ignoredCount).toBe(2);
    expect(result.selection.totalBytes).toBe(350);
  });

  it('explains a folder that only contains ignored files', () => {
    const result = buildCodebaseSelection([entry('proj/node_modules/a.js')], { fromFolder: true });
    expect(result).toMatchObject({ ok: false, error: expect.stringContaining('dependency or build folder') });
  });

  it('labels plain multi-file selections (no folder support) honestly', () => {
    const { entries, fromFolder } = entriesFromInput([file('a.py'), file('b.py')]);
    expect(fromFolder).toBe(false);
    const result = buildCodebaseSelection(entries, { fromFolder });
    expect(result.ok && result.selection.name).toBe('Selected files');
  });

  it('summarises languages by size and ignores unknown extensions', () => {
    const languages = summariseLanguages([
      { path: 'a.py', size: 300, file: file('a.py') },
      { path: 'b.ts', size: 100, file: file('b.ts') },
      { path: 'c.bin', size: 9999, file: file('c.bin') },
    ]);
    expect(languages.map((l) => [l.name, l.share])).toEqual([
      ['Python', 0.75],
      ['TypeScript', 0.25],
    ]);
  });

  it('only treats folder segments as ignored, not file names', () => {
    expect(isIgnoredPath('build/out.js')).toBe(true);
    expect(isIgnoredPath('src/build.py')).toBe(false);
  });
});

describe('citations', () => {
  it('turns known [n] markers into citations', () => {
    expect(splitCitations('Jupiter is largest [1]. It is heavy [1, 2].', new Set([1, 2]))).toEqual([
      { type: 'text', value: 'Jupiter is largest' },
      { type: 'cite', index: 1 },
      { type: 'text', value: '. It is heavy' },
      { type: 'cite', index: 1 },
      { type: 'cite', index: 2 },
      { type: 'text', value: '.' },
    ]);
  });

  it('leaves markers for unknown excerpts as plain text', () => {
    expect(splitCitations('Paris [3]', new Set([1]))).toEqual([{ type: 'text', value: 'Paris [3]' }]);
  });

  it('glues each chip run to the word before it and the punctuation after it', () => {
    const segments = splitCitations('Jupiter is largest [1]. It is heavy [1, 2].', new Set([1, 2]));
    expect(attachCitations(segments)).toEqual([
      { type: 'text', value: 'Jupiter is ' },
      { type: 'glued', before: 'largest', cites: [1], after: '.' },
      { type: 'text', value: ' It is ' },
      { type: 'glued', before: 'heavy', cites: [1, 2], after: '.' },
    ]);
    // Nothing is lost or reordered.
    const flat = attachCitations(segments)
      .map((p) => (p.type === 'text' ? p.value : `${p.before}${p.cites.map((c) => `[${c}]`).join('')}${p.after}`))
      .join('');
    expect(flat).toBe('Jupiter is largest[1]. It is heavy[1][2].');
  });
});

describe('formatBytes', () => {
  it.each([
    [512, '512 B'],
    [1024, '1 KB'],
    [1536, '1.5 KB'],
    [50 * 1024 * 1024, '50 MB'],
  ])('%i → %s', (bytes, text) => expect(formatBytes(bytes)).toBe(text));
});
