import { render, waitFor } from '@testing-library/react';
import { RobotMascot } from './RobotMascot';

// Pretend the browser has WebGL. jsdom can't actually create a context, so the 3D stage
// then fails to start, which also exercises the fallback.
vi.mock('./capabilities', async (original) => ({ ...(await original<typeof import('./capabilities')>()), hasWebGL: () => true }));

describe('while the 3D robot loads', () => {
  it('shows a loading percentage instead of the 2D robot', () => {
    const { container } = render(<RobotMascot pose="idle" />);
    const loader = container.querySelector('.robot__loader');
    expect(loader?.textContent).toMatch(/\d+%/);
    expect(container.querySelector('.robot')).toHaveAttribute('data-renderer', 'loading');
    expect(container.querySelector('.robot__layer[data-visible="true"] svg')).toBeNull();
  });

  it('shows the 2D robot instead if 3D can’t start, and the loader goes', async () => {
    const { container } = render(<RobotMascot pose="idle" />);
    await waitFor(() => expect(container.querySelector('.robot__layer[data-visible="true"] svg')).not.toBeNull());
    expect(container.querySelector('.robot__loader')).toBeNull();
  });

  it('shows the 2D robot at once, with no loader, when reduced motion is preferred', () => {
    const original = window.matchMedia;
    window.matchMedia = ((query: string) => ({ ...original(query), matches: query.includes('reduce') })) as typeof window.matchMedia;
    try {
      const { container } = render(<RobotMascot pose="idle" />);
      expect(container.querySelector('.robot__loader')).toBeNull();
      expect(container.querySelector('.robot__layer[data-visible="true"] svg')).not.toBeNull();
    } finally {
      window.matchMedia = original;
    }
  });
});
