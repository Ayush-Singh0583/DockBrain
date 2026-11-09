import { useCallback, useEffect, useState } from 'react';
import { applyTheme, readStoredTheme, storeTheme, systemTheme, type Theme } from './theme';

/** The theme that is showing, and a function that switches it. Follows the system until a choice is made. */
export function useTheme(): { theme: Theme; toggle: () => void } {
  const [choice, setChoice] = useState<Theme | null>(() => readStoredTheme());
  const [system, setSystem] = useState<Theme>(() => systemTheme());

  useEffect(() => {
    const query = window.matchMedia?.('(prefers-color-scheme: dark)');
    if (!query) return;
    const update = () => setSystem(query.matches ? 'dark' : 'light');
    query.addEventListener?.('change', update);
    return () => query.removeEventListener?.('change', update);
  }, []);

  const theme = choice ?? system;
  useEffect(() => applyTheme(choice, theme), [choice, theme]);

  const toggle = useCallback(() => {
    const next: Theme = theme === 'dark' ? 'light' : 'dark';
    storeTheme(next);
    setChoice(next);
  }, [theme]);

  return { theme, toggle };
}
