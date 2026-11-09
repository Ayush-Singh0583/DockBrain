import { useEffect, useRef, useState, type RefObject } from 'react';
import type { RobotStage } from './robot3d/stage';

/** A robot taken out of the page layout, fixed on screen at this box (CSS pixels). */
export interface Placement {
  left: number;
  top: number;
  width: number;
  height: number;
  /** Its width in the page layout; a lifted robot is never smaller than that. */
  minWidth: number;
}

const LONG_PRESS_MS = 350; // touch: hold this long to grab it, so swipes still scroll the page
const TOUCH_SLOP = 10; // pixels a finger may wander during the long press
const DRAG_START = 4; // pixels the pointer must move before the robot is lifted
const CALM_MS = 350; // it stops flying this long after it was last moved
const FULL_ASPECT = 7 / 6; // height / width of the whole robot (robot.css)
const CLICK_GUARD_MS = 500;
// A robot taken out of the layout is at least this wide: 16% of the window, from 180 to
// 300 px, so one lifted from a small slot doesn't stay tiny.
const LIFTED = { share: 0.16, min: 180, max: 300 };

function liftedWidth(minWidth: number): number {
  const viewport = document.documentElement.clientWidth || window.innerWidth;
  return Math.max(minWidth, Math.min(LIFTED.max, Math.max(LIFTED.min, viewport * LIFTED.share)));
}

function keepOnScreen(box: Placement): Placement {
  const width = document.documentElement.clientWidth || window.innerWidth;
  const height = document.documentElement.clientHeight || window.innerHeight;
  return {
    ...box,
    left: Math.min(Math.max(box.left, 0), Math.max(0, width - box.width)),
    top: Math.min(Math.max(box.top, 0), Math.max(0, height - box.height)),
  };
}

/** Something that just happened to the robot, and how many times before (from 0). */
export interface RobotMoment {
  kind: 'lift' | 'land' | 'poke';
  count: number;
}

interface Options {
  /** The robot's place in the page layout. */
  robotRef: RefObject<HTMLElement | null>;
  /** The 3D stage, used to match presses to the robot's shape while it is the visible robot. */
  stageRef: RefObject<RobotStage | null>;
  threeDShown: boolean;
}

/**
 * Lets the person pick the robot up and put it down anywhere on screen. Mouse and pen grab
 * it on press; touch needs a long press. It's lifted once the pointer starts moving, and it
 * flies (happy, eyes closed) only while it's being moved, settling when held still. A press without a drag
 * changes nothing. Only presses on the robot's body count, so the page around it stays
 * clickable. A dropped robot stays fixed where it was left, kept on screen, until the
 * screen changes.
 */
export function useRobotDrag({ robotRef, stageRef, threeDShown }: Options) {
  const [placement, setPlacement] = useState<Placement | null>(null);
  const [held, setHeld] = useState(false);
  const [flying, setFlying] = useState(false);
  const [moment, setMoment] = useState<RobotMoment | null>(null);
  const placed = useRef<Placement | null>(null);
  const threeD = useRef(threeDShown);

  useEffect(() => {
    threeD.current = threeDShown;
  }, [threeDShown]);

  useEffect(() => {
    let drag: { id: number; grabX: number; grabY: number; lastX: number; lastTime: number } | null = null;
    let pending: { id: number; x: number; y: number; timer: number } | null = null; // touch, before the long press
    let press: { id: number; x: number; y: number } | null = null; // grabbed, not yet moved
    let clickGuard: number | undefined;
    let calm: number | undefined;
    const root = document.documentElement;
    const counts = { lift: 0, land: 0, poke: 0 };
    const notify = (kind: RobotMoment['kind']) => setMoment({ kind, count: counts[kind]++ });

    const place = (box: Placement | null) => {
      placed.current = box;
      setPlacement(box);
    };

    const swallowClick = (event: Event) => {
      event.preventDefault();
      event.stopPropagation();
    };

    const onRobot = (event: PointerEvent) => {
      const robot = robotRef.current;
      if (!robot) return false;
      const stage = threeD.current ? stageRef.current : null;
      if (stage) return stage.hitTest(event.clientX, event.clientY);
      // Only the SVG robot's painted shapes take pointer events (robot.css).
      return event.target instanceof Node && robot.contains(event.target);
    };

    const pickUp = (id: number, x: number, y: number) => {
      const robot = robotRef.current;
      if (!robot) return;
      let box = placed.current;
      if (!box) {
        // Lift it out of the layout where it stands: whole, even from a head-and-shoulders slot.
        const home = robot.getBoundingClientRect();
        const width = liftedWidth(home.width);
        const height = width * FULL_ASPECT;
        const fx = home.width ? (x - home.left) / home.width : 0.5;
        const fy = home.height ? (y - home.top) / home.height : 0.5;
        box = { left: x - fx * width, top: y - fy * height, width, height, minWidth: home.width };
      }
      drag = { id, grabX: x - box.left, grabY: y - box.top, lastX: x, lastTime: performance.now() };
      place(box);
      setHeld(true);
      notify('lift');
    };

    // A release on the robot is followed by a click on whatever is under the pointer
    // (beneath the 3D robot, that's the page); swallow that one.
    const guardClick = () => {
      window.clearTimeout(clickGuard);
      window.addEventListener('click', swallowClick, { capture: true, once: true });
      clickGuard = window.setTimeout(() => window.removeEventListener('click', swallowClick, true), CLICK_GUARD_MS);
    };

    const fly = () => {
      setFlying(true);
      window.clearTimeout(calm);
      calm = window.setTimeout(() => setFlying(false), CALM_MS);
    };

    const release = () => {
      press = null;
      delete root.dataset.robotDrag;
      guardClick();
    };

    const drop = () => {
      if (!drag) return;
      drag = null;
      window.clearTimeout(calm);
      setFlying(false);
      setHeld(false);
      if (placed.current) place(keepOnScreen(placed.current));
      release();
      notify('land');
    };

    const cancelPending = () => {
      if (pending) window.clearTimeout(pending.timer);
      pending = null;
    };

    const grab = (id: number, x: number, y: number) => {
      press = { id, x, y };
      root.dataset.robotDrag = '';
    };

    const onDown = (event: PointerEvent) => {
      if (drag || pending || press) return;
      if (event.pointerType === 'mouse' && event.button !== 0) return;
      if (!onRobot(event)) return;
      const { pointerId: id, clientX: x, clientY: y } = event;
      if (event.pointerType === 'touch') {
        const timer = window.setTimeout(() => {
          pending = null;
          grab(id, x, y);
        }, LONG_PRESS_MS);
        pending = { id, x, y, timer };
        return;
      }
      event.preventDefault(); // no text selection or focus change under the robot
      event.stopPropagation();
      grab(id, x, y);
    };

    const onMove = (event: PointerEvent) => {
      if (pending && event.pointerId === pending.id) {
        if (Math.hypot(event.clientX - pending.x, event.clientY - pending.y) > TOUCH_SLOP) cancelPending();
        return;
      }
      if (press && event.pointerId === press.id) {
        if (Math.hypot(event.clientX - press.x, event.clientY - press.y) < DRAG_START) return;
        pickUp(press.id, press.x, press.y); // lifted where it was grabbed, then carried
        press = null;
      }
      if (drag && event.pointerId === drag.id && placed.current) {
        fly();
        const now = performance.now();
        stageRef.current?.nudge((event.clientX - drag.lastX) / Math.max(now - drag.lastTime, 8));
        drag.lastX = event.clientX;
        drag.lastTime = now;
        place({ ...placed.current, left: event.clientX - drag.grabX, top: event.clientY - drag.grabY });
        return;
      }
      // A mouse over the 3D robot shows that it can be grabbed (the SVG robot does this in CSS).
      if (event.pointerType === 'mouse' && threeD.current) {
        if (onRobot(event)) root.dataset.robotHover = '';
        else delete root.dataset.robotHover;
      }
    };

    const onUp = (event: PointerEvent) => {
      if (pending && event.pointerId === pending.id) cancelPending();
      if (press && event.pointerId === press.id) {
        release(); // pressed but never moved: a click on the robot
        notify('poke');
      }
      if (drag && event.pointerId === drag.id) drop();
    };
    const onBlur = () => {
      if (press) release();
      drop();
    };
    const onTouchMove = (event: TouchEvent) => {
      if (drag || press) event.preventDefault(); // carrying the robot, not scrolling the page
    };
    const onContextMenu = (event: Event) => {
      if (drag || pending || press) event.preventDefault();
    };
    const onResize = () => {
      const box = placed.current;
      if (!box || drag) return;
      const width = liftedWidth(box.minWidth); // stays in step with the window
      place(keepOnScreen({ ...box, width, height: width * FULL_ASPECT }));
    };

    window.addEventListener('pointerdown', onDown, true);
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
    window.addEventListener('pointercancel', onUp);
    window.addEventListener('blur', onBlur);
    window.addEventListener('touchmove', onTouchMove, { passive: false });
    window.addEventListener('contextmenu', onContextMenu, true);
    window.addEventListener('resize', onResize);
    return () => {
      window.removeEventListener('pointerdown', onDown, true);
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
      window.removeEventListener('pointercancel', onUp);
      window.removeEventListener('blur', onBlur);
      window.removeEventListener('touchmove', onTouchMove);
      window.removeEventListener('contextmenu', onContextMenu, true);
      window.removeEventListener('resize', onResize);
      window.removeEventListener('click', swallowClick, true);
      window.clearTimeout(clickGuard);
      window.clearTimeout(calm);
      cancelPending();
      delete root.dataset.robotDrag;
      delete root.dataset.robotHover;
    };
  }, [robotRef, stageRef]);

  return { placement, held, flying, moment };
}
