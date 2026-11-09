import { Moon, Sun } from 'lucide-react';
import { useTheme } from '../lib/useTheme';

/** The top bar's light/dark switch. Its icon and label show the theme you would switch to. */
export function ThemeToggle() {
  const { theme, toggle } = useTheme();
  const label = theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme';
  const Icon = theme === 'dark' ? Sun : Moon;
  return (
    <button type="button" className="icon-btn" aria-label={label} data-tooltip={label} onClick={toggle}>
      <Icon aria-hidden="true" />
    </button>
  );
}
