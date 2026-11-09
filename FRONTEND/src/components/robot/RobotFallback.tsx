import { useEffect, useRef } from 'react';
import { watchPointer } from './pointer';
import type { RobotRenderProps } from './types';

// Drawing areas: the whole robot, or head and shoulders for compact layouts.
const VIEWBOX = { full: '-67 -32 374 436', bust: '-10 -36 260 216' };
// The head's centre as a fraction of each drawing: drawn at (120, 86), scaled 1.39 from the
// neck at (120, 150), so it sits at (120, 61).
const HEAD = { full: { x: 0.5, y: (61 + 32) / 436 }, bust: { x: 0.5, y: (61 + 36) / 216 } };
// How far the eyes move toward the pointer (drawing units), and the pointer distance in
// pixels at which they're about three-quarters of the way there.
const GAZE = { x: 7, y: 5, reach: 260 };

/**
 * Lightweight SVG DockBrain robot, drawn to match the 3D model (GLB/dockbrain-companion.glb,
 * built by scripts/build-robot-model.mjs). Used while the 3D robot loads, when WebGL is
 * unavailable, and (without any animation) for people who prefer reduced motion.
 * Poses are CSS transforms keyed off data attributes; see robot.css.
 */
export function RobotFallback({
  pose,
  facing,
  crop,
  animated,
  followPointer = false,
}: RobotRenderProps & { animated: boolean; followPointer?: boolean }) {
  const svgRef = useRef<SVGSVGElement>(null);
  const gazeRef = useRef<SVGGElement>(null);

  // Eyes follow the pointer, written straight to the element: no re-render per movement.
  useEffect(() => {
    const gaze = gazeRef.current;
    if (!gaze) return;
    gaze.style.transform = '';
    if (!followPointer || pose === 'flying') return; // its eyes are closed
    return watchPointer((point) => {
      const svg = svgRef.current;
      if (!point || !svg) {
        gaze.style.transform = '';
        return;
      }
      const rect = svg.getBoundingClientRect();
      const head = HEAD[crop];
      const dx = Math.tanh((point.x - (rect.left + rect.width * head.x)) / GAZE.reach) * GAZE.x;
      const dy = Math.tanh((point.y - (rect.top + rect.height * head.y)) / GAZE.reach) * GAZE.y;
      gaze.style.transform = `translate(${dx.toFixed(2)}px, ${dy.toFixed(2)}px)`;
    });
  }, [followPointer, pose, crop]);

  return (
    <svg
      ref={svgRef}
      className="rbt"
      viewBox={VIEWBOX[crop]}
      data-pose={pose}
      data-facing={facing}
      data-animated={animated}
      aria-hidden="true"
      focusable="false"
    >
      <g className="rbt-figure">
        {crop === 'full' && <ellipse className="rbt-shadow" cx="120" cy="400" rx="84" ry="4" />}
        <g className="rbt-torso">
          {/* Big plain white round body (its radius is the face screen's width) with a chest light. */}
          <circle className="rbt-shell" cx="120" cy="271" r="122" />
          <path className="rbt-seam" d="M36 359q84 22 168 0" />
          <circle className="rbt-pale" cx="164" cy="212" r="15.5" />
          <circle className="rbt-light rbt-chest-light" cx="164" cy="212" r="11" />

          {/* The head, drawn at its original size and scaled up from the neck to suit the big body. */}
          <g transform="translate(120 150) scale(1.39) translate(-120 -150)">
            <g className="rbt-head">
              {/* Elliptical head with a dark oval face screen, glowing arcs at its diagonals. */}
              <ellipse className="rbt-shell" cx="120" cy="86" rx="88" ry="64" />
              <ellipse className="rbt-screen" cx="120" cy="87" rx="70" ry="46" />
              <path className="rbt-bracket" d="M173.4 65.1A63.0 41.4 0 0 0 153.4 51.9M86.6 51.9A63.0 41.4 0 0 0 66.6 65.1M66.6 108.9A63.0 41.4 0 0 0 86.6 122.1M153.4 122.1A63.0 41.4 0 0 0 173.4 108.9" />

              <g className="rbt-eyes">
                <g className="rbt-gaze" ref={gazeRef}>
                  <g className="rbt-eyes-open">
                    <ellipse className="rbt-eye" cx="98" cy="84" rx="9.5" ry="13" />
                    <ellipse className="rbt-eye" cx="142" cy="84" rx="9.5" ry="13" />
                    <circle className="rbt-shine" cx="95" cy="79" r="3" />
                    <circle className="rbt-shine" cx="139" cy="79" r="3" />
                    <circle className="rbt-shine" cx="101.5" cy="89.5" r="1.4" />
                    <circle className="rbt-shine" cx="145.5" cy="89.5" r="1.4" />
                  </g>
                  <g className="rbt-eyes-happy">
                    <path className="rbt-stroke" d="M88 89q10-15 20 0" />
                    <path className="rbt-stroke" d="M132 89q10-15 20 0" />
                  </g>
                </g>
              </g>
              {/* One mouth per mood; robot.css shows the one for the current pose. */}
              <path className="rbt-stroke rbt-mouth" d="M112 104q8 7 16 0" />
              <g className="rbt-mouth-grin">
                <path className="rbt-eye" d="M110 102h20a10 10 0 0 1-20 0z" />
                <ellipse className="rbt-tongue" cx="120" cy="108" rx="5.5" ry="3" />
              </g>
              <ellipse className="rbt-mouth-oh" cx="120" cy="107" rx="4" ry="4.5" />
              </g>
          </g>

          {/* Arms: plain white egg-shaped hands, wide at the shoulder, narrowing to the tip.
              Drawn last, so a raised arm waves in front of the head, not behind it. */}
          <g className="rbt-arm rbt-arm--l">
            <path className="rbt-shell" d="M0 28C10 28 17 10 17 -6C17 -20 9 -28 0 -28C-9 -28 -17 -20 -17 -6C-17 10 -10 28 0 28Z" transform="translate(-27 247) rotate(22) scale(1.73)" />
          </g>
          <g className="rbt-arm rbt-arm--r">
            <path className="rbt-shell" d="M0 28C10 28 17 10 17 -6C17 -20 9 -28 0 -28C-9 -28 -17 -20 -17 -6C-17 10 -10 28 0 28Z" transform="translate(267 247) rotate(-22) scale(1.73)" />
          </g>
        </g>
      </g>
    </svg>
  );
}
