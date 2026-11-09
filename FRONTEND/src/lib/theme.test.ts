import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import indexHtml from '../../index.html?raw';
import { applyTheme, readStoredTheme, storeTheme, systemTheme } from './theme';

type Store = Pick<Storage, 'getItem' | 'setItem'>;

/** A storage holding `items`, or one that refuses reads or writes, as a locked-down browser does. */
function storage(items: Record<string, string> = {}, refuses: 'reads' | 'writes' | null = null): Store & { items: Record<string, string> } {
  return {
    items,
    getItem: (key) => {
      if (refuses === 'reads') throw new DOMException('Access denied', 'SecurityError');
      return items[key] ?? null;
    },
    setItem: (key, value) => {
      if (refuses === 'writes') throw new DOMException('Quota exceeded', 'QuotaExceededError');
      items[key] = value;
    },
  };
}

beforeEach(() => {
  localStorage.clear();
  document.documentElement.removeAttribute('data-theme');
  document.head.querySelector('meta[name="theme-color"]')?.remove();
});
afterEach(() => localStorage.clear());

describe('readStoredTheme', () => {
  it.each([
    ['light', 'light'],
    ['dark', 'dark'],
    ['blue', null],
    ['DARK', null],
    ['', null],
  ])('reads a stored %j as %j', (stored, expected) => {
    const found = readStoredTheme(storage({ 'dockbrain-theme': stored }));
    expect(found).toBe(expected);
  });

  it('finds nothing when nothing was chosen yet', () => {
    expect(readStoredTheme(storage())).toBeNull();
  });

  it('treats storage the browser refuses to read as no choice', () => {
    expect(readStoredTheme(storage({ 'dockbrain-theme': 'dark' }, 'reads'))).toBeNull();
  });
});

describe('storeTheme', () => {
  it('keeps the choice, and a refused write is not an error', () => {
    const kept = storage();
    storeTheme('dark', kept);
    expect(readStoredTheme(kept)).toBe('dark');
    expect(() => storeTheme('light', storage({}, 'writes'))).not.toThrow();
  });
});

describe('applyTheme', () => {
  it('marks the page with an explicit choice, and clears the mark to follow the system again', () => {
    applyTheme('dark', 'dark');
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
    applyTheme('light', 'light');
    expect(document.documentElement.getAttribute('data-theme')).toBe('light');
    applyTheme(null, 'dark');
    expect(document.documentElement.hasAttribute('data-theme')).toBe(false);
  });

  it('keeps the browser’s own chrome (the phone address bar) in step with the visible theme', () => {
    const colour = () => document.head.querySelector('meta[name="theme-color"]')?.getAttribute('content');
    applyTheme('light', 'light');
    const light = colour();
    applyTheme(null, 'dark'); // following a dark system setting still shows the dark theme
    const dark = colour();
    expect(light).toMatch(/^#[0-9a-f]{6}$/);
    expect(dark).toMatch(/^#[0-9a-f]{6}$/);
    expect(dark).not.toBe(light);
    expect(document.head.querySelectorAll('meta[name="theme-color"]')).toHaveLength(1);
  });
});

describe('systemTheme', () => {
  it.each([
    { asksForDark: true, expected: 'dark' },
    { asksForDark: false, expected: 'light' },
  ])('is $expected when the system asks for dark: $asksForDark', ({ asksForDark, expected }) => {
    vi.spyOn(window, 'matchMedia').mockImplementation(
      (query) => ({ matches: asksForDark && query === '(prefers-color-scheme: dark)', media: query }) as MediaQueryList,
    );
    expect(systemTheme()).toBe(expected);
  });
});

describe('the startup script in index.html (it runs before the app, so the page never flashes the wrong theme)', () => {
  const runStartupScript = () => {
    const script = indexHtml.match(/<script id="theme-init">([\s\S]*?)<\/script>/)?.[1];
    expect(script, 'index.html needs an inline <script id="theme-init">').toBeTruthy();
    new Function(script!)();
  };

  it('applies the choice the toggle saved', () => {
    storeTheme('dark');
    runStartupScript();
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
  });

  it('leaves the page following the system when nothing, or junk, was saved', () => {
    runStartupScript();
    expect(document.documentElement.hasAttribute('data-theme')).toBe(false);
    localStorage.setItem('dockbrain-theme', 'purple');
    runStartupScript();
    expect(document.documentElement.hasAttribute('data-theme')).toBe(false);
  });

  it('survives storage that throws', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new DOMException('Access denied', 'SecurityError');
    });
    expect(runStartupScript).not.toThrow();
    expect(document.documentElement.hasAttribute('data-theme')).toBe(false);
  });
});
