import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ThemeToggle } from './ThemeToggle';

/** Stands in for the operating system's dark-mode setting, which jsdom doesn't have. */
function systemSetting(startsDark: boolean) {
  let dark = startsDark;
  const listeners = new Set<() => void>();
  vi.spyOn(window, 'matchMedia').mockImplementation(
    (query) =>
      ({
        get matches() {
          return dark && query === '(prefers-color-scheme: dark)';
        },
        media: query,
        addEventListener: (_type: string, listener: () => void) => listeners.add(listener),
        removeEventListener: (_type: string, listener: () => void) => listeners.delete(listener),
      }) as unknown as MediaQueryList,
  );
  return {
    change(next: boolean) {
      dark = next;
      act(() => listeners.forEach((listener) => listener()));
    },
  };
}

const html = () => document.documentElement;
const toggle = (name: 'Switch to dark theme' | 'Switch to light theme') => screen.getByRole('button', { name });

beforeEach(() => {
  localStorage.clear();
  html().removeAttribute('data-theme');
});

describe('ThemeToggle', () => {
  it('switches to dark and back', async () => {
    systemSetting(false);
    const user = userEvent.setup();
    render(<ThemeToggle />);

    await user.click(toggle('Switch to dark theme'));
    expect(html()).toHaveAttribute('data-theme', 'dark');
    await user.click(toggle('Switch to light theme'));
    expect(html()).toHaveAttribute('data-theme', 'light');
    expect(screen.getByRole('button', { name: 'Switch to dark theme' })).toBeInTheDocument();
  });

  it('remembers the choice for the next visit', async () => {
    systemSetting(false);
    const user = userEvent.setup();
    const first = render(<ThemeToggle />);
    await user.click(toggle('Switch to dark theme'));
    first.unmount();
    html().removeAttribute('data-theme'); // a fresh page load

    render(<ThemeToggle />);
    expect(html()).toHaveAttribute('data-theme', 'dark');
    expect(toggle('Switch to light theme')).toBeInTheDocument();
  });

  it('follows a dark system setting until a choice is made, without pinning the page to it', async () => {
    systemSetting(true);
    const user = userEvent.setup();
    render(<ThemeToggle />);

    expect(toggle('Switch to light theme')).toBeInTheDocument();
    expect(html().hasAttribute('data-theme')).toBe(false); // the stylesheet follows the system itself
    await user.click(toggle('Switch to light theme'));
    expect(html()).toHaveAttribute('data-theme', 'light');
  });

  it('follows the system while nothing has been chosen, and stops once something is', async () => {
    const system = systemSetting(false);
    const user = userEvent.setup();
    render(<ThemeToggle />);
    expect(toggle('Switch to dark theme')).toBeInTheDocument();

    system.change(true);
    expect(toggle('Switch to light theme')).toBeInTheDocument();

    await user.click(toggle('Switch to light theme')); // an explicit light choice
    system.change(false);
    system.change(true);
    expect(toggle('Switch to dark theme')).toBeInTheDocument();
  });

  it('still switches when the browser refuses to save the choice', async () => {
    systemSetting(false);
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('Quota exceeded', 'QuotaExceededError');
    });
    const user = userEvent.setup();
    render(<ThemeToggle />);

    await user.click(toggle('Switch to dark theme'));
    expect(html()).toHaveAttribute('data-theme', 'dark');
    expect(toggle('Switch to light theme')).toBeInTheDocument();
  });
});
