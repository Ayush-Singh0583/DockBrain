/**
 * The light and dark themes. The stylesheet follows the operating system by itself. The switch
 * in the top bar overrides that, and the choice is kept in this browser. `<html data-theme>` is
 * set only for an explicit choice; index.html applies it before the app loads, so the page
 * never flashes the wrong theme.
 */
export type Theme = 'light' | 'dark';

const KEY = 'dockbrain-theme'; // also read by the startup script in index.html
const DARK_QUERY = '(prefers-color-scheme: dark)';
/** The stage colour of each theme (tokens.css, --band-bg), for the phone's address bar. */
const BROWSER_CHROME: Record<Theme, string> = { light: '#2152dc', dark: '#0e1731' };

function browserStorage(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null; // some privacy settings make even looking at localStorage throw
  }
}

export function readStoredTheme(storage: Pick<Storage, 'getItem'> | null = browserStorage()): Theme | null {
  try {
    const stored = storage?.getItem(KEY);
    return stored === 'light' || stored === 'dark' ? stored : null;
  } catch {
    return null;
  }
}

export function storeTheme(theme: Theme, storage: Pick<Storage, 'setItem'> | null = browserStorage()): void {
  try {
    storage?.setItem(KEY, theme);
  } catch {
    // A browser that won't save still switches for this visit.
  }
}

export function systemTheme(): Theme {
  return window.matchMedia?.(DARK_QUERY).matches ? 'dark' : 'light';
}

/** `choice` is what the person picked, or null to follow the system; `visible` is what shows. */
export function applyTheme(choice: Theme | null, visible: Theme): void {
  const root = document.documentElement;
  if (choice) root.setAttribute('data-theme', choice);
  else root.removeAttribute('data-theme');

  let meta = document.head.querySelector<HTMLMetaElement>('meta[name="theme-color"]');
  if (!meta) {
    meta = document.createElement('meta');
    meta.name = 'theme-color';
    document.head.append(meta);
  }
  meta.content = BROWSER_CHROME[visible];
}
