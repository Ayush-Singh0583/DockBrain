/**
 * Where the mouse or pen is on screen, shared by every robot so their eyes can follow it.
 * One passive listener on the window, added while any robot is watching. Nothing is
 * stored or sent anywhere; the position is forgotten when the pointer leaves the window.
 */
export interface PointerPoint {
  x: number;
  y: number;
}

type Listener = (point: PointerPoint | null) => void;

let point: PointerPoint | null = null;
let watchers = 0;
const listeners = new Set<Listener>();

function update(next: PointerPoint | null) {
  point = next;
  listeners.forEach((listener) => listener(point));
}

const onMove = (event: PointerEvent) => update({ x: event.clientX, y: event.clientY });
const onLeave = (event: MouseEvent) => {
  if (!event.relatedTarget) update(null);
};
const onBlur = () => update(null);

/** Starts watching the pointer; call the returned function to stop. */
export function watchPointer(listener?: Listener): () => void {
  if (watchers++ === 0) {
    window.addEventListener('pointermove', onMove, { passive: true });
    document.addEventListener('mouseout', onLeave);
    window.addEventListener('blur', onBlur);
  }
  if (listener) listeners.add(listener);
  return () => {
    if (listener) listeners.delete(listener);
    if (--watchers === 0) {
      window.removeEventListener('pointermove', onMove);
      document.removeEventListener('mouseout', onLeave);
      window.removeEventListener('blur', onBlur);
      point = null;
    }
  };
}

/** The latest pointer position, or null if it's outside the window or unknown. */
export function pointerPoint(): PointerPoint | null {
  return point;
}
