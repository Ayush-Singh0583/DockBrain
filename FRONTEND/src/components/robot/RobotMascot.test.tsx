import { act, fireEvent, render } from '@testing-library/react';
import { RobotMascot, type RobotMascotProps } from './RobotMascot';

// jsdom has no WebGL, so these exercise the SVG robot; the 3D robot shares the same
// pick-up logic and differs only in how a press is matched to its body.

const HOME = new DOMRect(100, 200, 240, 280); // where the robot sits on the page

function setup(props: Partial<RobotMascotProps> = {}) {
  const onBehind = vi.fn();
  const utils = render(
    <>
      <button type="button" onClick={onBehind}>
        Behind the robot
      </button>
      <RobotMascot pose="idle" {...props} />
    </>,
  );
  const robot = utils.container.querySelector<HTMLElement>('.robot')!;
  vi.spyOn(robot, 'getBoundingClientRect').mockReturnValue(HOME);
  const body = robot.querySelector<HTMLElement>('.robot__body')!;
  const svg = () => robot.querySelector('svg')!;
  const torso = () => robot.querySelector('.rbt-torso .rbt-shell')!; // a painted part of the robot
  return { ...utils, robot, body, svg, torso, onBehind, behind: utils.getByRole('button', { name: 'Behind the robot' }) };
}

const at = (x: number, y: number, pointerType = 'mouse') => ({
  clientX: x,
  clientY: y,
  button: 0,
  pointerId: pointerType === 'touch' ? 7 : 1,
  pointerType,
  isPrimary: true,
});

describe('picking up the robot', () => {
  it('stays put and calm when its body is only pressed or clicked', () => {
    const { robot, body, svg, torso } = setup({ pose: 'greet' });
    fireEvent.pointerDown(torso(), at(150, 250));
    fireEvent.pointerMove(window, at(152, 251)); // a hand's tremble, not a drag
    expect(robot).toHaveAttribute('data-held', 'false');
    expect(svg()).toHaveAttribute('data-pose', 'greet');
    fireEvent.pointerUp(window, at(152, 251));
    expect(robot).toHaveAttribute('data-placed', 'false');
    expect(body.style.position).toBe('');
  });

  it('lifts the robot once it is dragged, and it flies happily while moving', () => {
    const { robot, body, svg, torso } = setup({ pose: 'greet' });
    fireEvent.pointerDown(torso(), at(150, 250));
    fireEvent.pointerMove(window, at(160, 250));
    expect(robot).toHaveAttribute('data-held', 'true');
    expect(svg()).toHaveAttribute('data-pose', 'flying');
    expect(body.style.position).toBe('fixed');
    expect([body.style.left, body.style.top]).toEqual(['110px', '200px']); // grabbed where it was pressed
  });

  it('settles when held still, and flies again when moved', () => {
    vi.useFakeTimers();
    try {
      const { robot, svg, torso } = setup({ pose: 'greet' });
      fireEvent.pointerDown(torso(), at(150, 250));
      fireEvent.pointerMove(window, at(200, 260));
      expect(svg()).toHaveAttribute('data-pose', 'flying');
      act(() => vi.advanceTimersByTime(600));
      expect(robot).toHaveAttribute('data-held', 'true'); // still in hand
      expect(svg()).toHaveAttribute('data-pose', 'greet');
      fireEvent.pointerMove(window, at(260, 280));
      expect(svg()).toHaveAttribute('data-pose', 'flying');
    } finally {
      vi.useRealTimers();
    }
  });

  it('carries it with the pointer and leaves it where it is dropped', () => {
    const { robot, body, svg, torso } = setup({ pose: 'greet' });
    fireEvent.pointerDown(torso(), at(150, 250));
    fireEvent.pointerMove(window, at(450, 350));
    expect([body.style.left, body.style.top]).toEqual(['400px', '300px']);

    fireEvent.pointerUp(window, at(450, 350));
    expect(robot).toHaveAttribute('data-held', 'false');
    expect(svg()).toHaveAttribute('data-pose', 'greet');
    expect(body.style.position).toBe('fixed');
    expect([body.style.left, body.style.top]).toEqual(['400px', '300px']);
  });

  it('can be picked up again from where it was left', () => {
    const { body, torso } = setup();
    fireEvent.pointerDown(torso(), at(150, 250));
    fireEvent.pointerMove(window, at(450, 350));
    fireEvent.pointerUp(window, at(450, 350));
    fireEvent.pointerDown(torso(), at(460, 360));
    fireEvent.pointerMove(window, at(470, 380));
    expect([body.style.left, body.style.top]).toEqual(['410px', '320px']);
  });

  it('keeps a dropped robot on the screen', () => {
    const { body, torso } = setup();
    fireEvent.pointerDown(torso(), at(150, 250));
    fireEvent.pointerMove(window, at(5000, -900));
    fireEvent.pointerUp(window, at(5000, -900));
    expect(body.style.left).toBe(`${window.innerWidth - 240}px`);
    expect(body.style.top).toBe('0px');
  });

  it('ignores presses on the page beside the robot', async () => {
    const { robot, behind, onBehind } = setup();
    fireEvent.pointerDown(behind, at(10, 10));
    expect(robot).toHaveAttribute('data-held', 'false');
    fireEvent.click(behind);
    expect(onBehind).toHaveBeenCalledTimes(1);
  });

  it('doesn’t let a press on the robot click what is underneath', () => {
    const { behind, onBehind, torso } = setup();
    for (const end of [at(150, 250), at(300, 300)]) {
      // a click on the robot, then a drag
      fireEvent.pointerDown(torso(), at(150, 250));
      fireEvent.pointerMove(window, end);
      fireEvent.pointerUp(window, end);
      fireEvent.click(behind); // the click a browser sends after the release
      expect(onBehind).not.toHaveBeenCalled();
    }
    fireEvent.click(behind); // later clicks work
    expect(onBehind).toHaveBeenCalledTimes(1);
  });

  it('needs a long press by touch, so a swipe across the robot still scrolls', () => {
    vi.useFakeTimers();
    try {
      const { robot, torso } = setup();
      fireEvent.pointerDown(torso(), at(150, 250, 'touch'));
      act(() => vi.advanceTimersByTime(500));
      fireEvent.pointerMove(window, at(170, 290, 'touch')); // long press, then drag
      expect(robot).toHaveAttribute('data-held', 'true');
      fireEvent.pointerUp(window, at(170, 290, 'touch'));

      fireEvent.pointerDown(torso(), at(150, 250, 'touch'));
      fireEvent.pointerMove(window, at(150, 300, 'touch')); // a swipe
      act(() => vi.advanceTimersByTime(500));
      fireEvent.pointerMove(window, at(150, 350, 'touch')); // still swiping after the long-press time
      expect(robot).toHaveAttribute('data-held', 'false');
    } finally {
      vi.useRealTimers();
    }
  });

  it('grows a small robot to a comfortable size when it is lifted, and keeps it in step with the window', () => {
    const { body, robot, torso } = setup({ crop: 'bust' });
    vi.spyOn(robot, 'getBoundingClientRect').mockReturnValue(new DOMRect(100, 200, 120, 100));
    fireEvent.pointerDown(torso(), at(160, 250));
    fireEvent.pointerMove(window, at(400, 300));
    fireEvent.pointerUp(window, at(400, 300));
    expect(parseFloat(body.style.width)).toBeGreaterThanOrEqual(180);
    expect(parseFloat(body.style.height)).toBeCloseTo((parseFloat(body.style.width) * 7) / 6, 1);

    const width = window.innerWidth;
    try {
      window.innerWidth = 2400; // a wide screen: 16% of it, capped at 300
      fireEvent(window, new Event('resize'));
      expect(body.style.width).toBe('300px');
    } finally {
      window.innerWidth = width;
    }
  });

  it('faces the viewer and stops pointing once it is put somewhere else', () => {
    const { svg, torso } = setup({ pose: 'point', facing: 'right' });
    expect(svg()).toHaveAttribute('data-facing', 'right');
    fireEvent.pointerDown(torso(), at(150, 250));
    fireEvent.pointerMove(window, at(600, 300));
    fireEvent.pointerUp(window, at(600, 300));
    expect(svg()).toHaveAttribute('data-facing', 'front');
    expect(svg()).toHaveAttribute('data-pose', 'idle');
  });

  it('lifts a head-and-shoulders robot out whole, without moving the page', () => {
    const { robot, svg, torso } = setup({ crop: 'bust' });
    expect(svg().getAttribute('viewBox')).toBe('-10 -36 260 216');
    fireEvent.pointerDown(torso(), at(150, 250));
    fireEvent.pointerMove(window, at(180, 280));
    expect(svg().getAttribute('viewBox')).toBe('-67 -32 374 436');
    expect(robot).toHaveAttribute('data-crop', 'bust'); // its place in the layout keeps its shape
  });
});

describe('the robot’s eyes', () => {
  function gazeOffset(svg: SVGSVGElement) {
    // "translate(4px, 2px)", or "translate(4px)" when the second offset is zero.
    const match = /translate\((-?[\d.]+)px(?:, (-?[\d.]+)px)?\)/.exec(svg.querySelector<SVGGElement>('.rbt-gaze')!.style.transform);
    return match ? { x: Number(match[1]), y: Number(match[2] ?? 0) } : { x: 0, y: 0 };
  }

  it('follow the pointer', () => {
    const { svg } = setup();
    vi.spyOn(svg(), 'getBoundingClientRect').mockReturnValue(HOME);
    const head = { x: 100 + 240 / 2, y: 200 + (280 * (61 + 32)) / 436 }; // the head's centre on screen
    fireEvent.pointerMove(window, at(head.x + 600, head.y));
    expect(gazeOffset(svg()).x).toBeGreaterThan(3);
    expect(Math.abs(gazeOffset(svg()).y)).toBeLessThan(0.5);
    fireEvent.pointerMove(window, at(head.x, head.y - 600));
    expect(gazeOffset(svg()).y).toBeLessThan(-3);
  });

  it('stay still when reduced motion is preferred', () => {
    const original = window.matchMedia;
    window.matchMedia = ((query: string) => ({ ...original(query), matches: query.includes('reduce') })) as typeof window.matchMedia;
    try {
      const { svg } = setup();
      vi.spyOn(svg(), 'getBoundingClientRect').mockReturnValue(HOME);
      fireEvent.pointerMove(window, at(900, 272));
      expect(gazeOffset(svg())).toEqual({ x: 0, y: 0 });
    } finally {
      window.matchMedia = original;
    }
  });
});

describe('what the robot says', () => {
  const quip = (robot: HTMLElement) => robot.querySelector('.robot__quip')?.textContent ?? null;

  it('says it’s flying while being moved, and something else when held still', () => {
    vi.useFakeTimers();
    try {
      const { robot, torso } = setup();
      expect(quip(robot)).toBeNull();
      fireEvent.pointerDown(torso(), at(150, 250));
      expect(quip(robot)).toBeNull(); // a press alone says nothing yet
      fireEvent.pointerMove(window, at(200, 260));
      expect(quip(robot)).toBe('Wooo, I’m flying!');
      act(() => vi.advanceTimersByTime(600));
      expect(quip(robot)).toBe('Nice view from up here.');
    } finally {
      vi.useRealTimers();
    }
  });

  it('is relieved when put down, then goes quiet', () => {
    vi.useFakeTimers();
    try {
      const { robot, torso } = setup();
      fireEvent.pointerDown(torso(), at(150, 250));
      fireEvent.pointerMove(window, at(300, 300));
      fireEvent.pointerUp(window, at(300, 300));
      expect(quip(robot)).toBe('Phew, solid ground!');
      act(() => vi.advanceTimersByTime(3000));
      expect(quip(robot)).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it('giggles when clicked', () => {
    const { robot, torso } = setup();
    fireEvent.pointerDown(torso(), at(150, 250));
    fireEvent.pointerUp(window, at(150, 250));
    expect(quip(robot)).toBe('Hehe, that tickles!');
  });

  it('says something different the next time', () => {
    const { robot, torso } = setup();
    for (const [expected, x] of [['Wooo, I’m flying!', 300], ['Wheee!', 450]] as const) {
      fireEvent.pointerDown(torso(), at(x - 150, 250));
      fireEvent.pointerMove(window, at(x, 300));
      expect(quip(robot)).toBe(expected);
      fireEvent.pointerUp(window, at(x, 300));
    }
  });
});
