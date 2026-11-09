import { useEffect, useState } from 'react';

let webglSupport: boolean | undefined;

/** Whether this browser can create a WebGL context. Checked once and cached. */
export function hasWebGL(): boolean {
  if (webglSupport !== undefined) return webglSupport;
  try {
    const canvas = document.createElement('canvas');
    const context = canvas.getContext('webgl2') ?? canvas.getContext('webgl');
    webglSupport = Boolean(context);
    // Release the probe context straight away; browsers cap live contexts.
    (context as WebGLRenderingContext | null)?.getExtension('WEBGL_lose_context')?.loseContext();
  } catch {
    webglSupport = false;
  }
  return webglSupport;
}

const REDUCED = '(prefers-reduced-motion: reduce)';

export function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(() => typeof window !== 'undefined' && window.matchMedia?.(REDUCED).matches === true);
  useEffect(() => {
    const query = window.matchMedia?.(REDUCED);
    if (!query) return;
    const update = () => setReduced(query.matches);
    update();
    query.addEventListener('change', update);
    return () => query.removeEventListener('change', update);
  }, []);
  return reduced;
}

/** `?robot=2d` forces the SVG robot, e.g. to compare renderers or on slow machines. */
export function robotForced2d(): boolean {
  return typeof window !== 'undefined' && new URLSearchParams(window.location.search).get('robot') === '2d';
}

// The DockBrain robot, read from the repository's GLB/ folder. Vite serves it in
// development and copies it into the build, so there is no second copy to keep in step.
import dockbrainRobotUrl from '../../../../GLB/dockbrain-companion.glb?url';

/**
 * The robot model to load: unset or empty means the DockBrain robot from GLB/, "none"
 * means the built-in robot made from simple shapes, and anything else is a model URL
 * (see HANDOFF.md, "Replacing the robot with a GLB").
 */
export function resolveRobotGlbUrl(setting: string | undefined, dockbrainRobot: string): string {
  const value = setting?.trim() ?? '';
  if (value.toLowerCase() === 'none') return '';
  return value || dockbrainRobot;
}

export const ROBOT_GLB_URL: string = resolveRobotGlbUrl(import.meta.env.VITE_ROBOT_GLB_URL, dockbrainRobotUrl);
