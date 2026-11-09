import { Component, lazy, Suspense, useCallback, useEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react';
import { RobotFallback } from './RobotFallback';
import { hasWebGL, robotForced2d, usePrefersReducedMotion } from './capabilities';
import type { RobotStage } from './robot3d/stage';
import type { RobotCrop, RobotFacing, RobotPose } from './types';
import { useRobotDrag, type RobotMoment } from './useRobotDrag';
import './robot.css';

// three.js is only downloaded when a 3D robot is actually shown.
const Robot3D = lazy(() => import('./robot3d/Robot3D'));

export interface RobotMascotProps {
  pose?: RobotPose;
  facing?: RobotFacing;
  size?: 'xl' | 'lg' | 'md' | 'sm';
  crop?: RobotCrop;
  className?: string;
}

// What the robot says when it's picked up and put down. Each moment cycles through its lines.
const QUIPS = {
  flying: ['Wooo, I’m flying!', 'Wheee!', 'Whoa, whoa, whoa!', 'Up, up and away!'],
  held: ['Nice view from up here.', 'Are we there yet?', 'Um… you can put me down now.'],
  land: ['Phew, solid ground!', 'Nice landing!', 'I like it here.'],
  poke: ['Hehe, that tickles!', 'Boop!', 'Hi there!'],
};
const QUIP_MS = 2000; // how long a line stays up after landing or a click

const say = (lines: string[], count: number) => lines[count % lines.length]!;

/** The line to show: while held, flying or hanging still; for a moment after landing or a click. */
function useQuip(held: boolean, flying: boolean, moment: RobotMoment | null): string | null {
  const [lingering, setLingering] = useState<RobotMoment | null>(null);
  useEffect(() => {
    if (!moment || moment.kind === 'lift') return setLingering(null);
    setLingering(moment);
    const timer = window.setTimeout(() => setLingering(null), QUIP_MS);
    return () => window.clearTimeout(timer);
  }, [moment]);
  if (held) {
    const flight = moment?.kind === 'lift' ? moment.count : 0;
    return say(flying ? QUIPS.flying : QUIPS.held, flight);
  }
  if (lingering?.kind === 'land' || lingering?.kind === 'poke') return say(QUIPS[lingering.kind], lingering.count);
  return null;
}

class Robot3DBoundary extends Component<{ onError: () => void; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidCatch() {
    this.props.onError();
  }
  render() {
    return this.state.failed ? null : this.props.children;
  }
}

/**
 * The DockBrain robot. Decorative (hidden from assistive technology): the speech
 * bubbles next to it carry the meaning.
 *
 * While the 3D robot loads it shows a progress ring with a percentage, then the 3D robot
 * once it has drawn its first frame. It uses the SVG robot instead when WebGL is missing or
 * fails, when the person prefers reduced motion, or with ?robot=2d.
 *
 * Its eyes follow the pointer (not with reduced motion). It can be picked up, flying
 * happily (eyes closed, grinning) while it's being moved, and put down anywhere on screen (useRobotDrag). It says a short
 * line in a bubble while it's carried, when it lands and when it's clicked; like the robot,
 * the bubble is decorative and hidden from assistive technology. Its place in the layout
 * stays empty meanwhile, so nothing on the page moves.
 */
export function RobotMascot({ pose = 'idle', facing = 'front', size = 'lg', crop = 'full', className }: RobotMascotProps) {
  const reducedMotion = usePrefersReducedMotion();
  const [failed, setFailed] = useState(false);
  const [ready, setReady] = useState(false);
  // How far the model has downloaded (0–1), or null while the 3D engine itself loads.
  const [downloaded, setDownloaded] = useState<number | null>(null);
  const use3d = !reducedMotion && !failed && !robotForced2d() && hasWebGL();
  const showSvg = !use3d;
  // The engine counts for the first 30%, the model's bytes for the next 65%, and the first
  // drawn frame for the last 5%.
  const loaded = ready ? 1 : downloaded === null ? 0 : 0.3 + 0.65 * downloaded;

  const robotRef = useRef<HTMLDivElement>(null);
  const stageRef = useRef<RobotStage | null>(null);
  const { placement, held, flying, moment } = useRobotDrag({ robotRef, stageRef, threeDShown: use3d && ready });
  const quip = useQuip(held, flying, moment);
  // Only while being moved. Set down somewhere else, it faces the viewer: pointing at what
  // was beside it in the layout would make no sense there.
  const shownPose: RobotPose = flying ? 'flying' : placement && pose === 'point' ? 'idle' : pose;
  const shownFacing: RobotFacing = placement ? 'front' : facing;
  const shownCrop: RobotCrop = placement ? 'full' : crop; // lifted out whole

  const handleReady = useCallback(() => setReady(true), []);
  const handleProgress = useCallback((fraction: number) => setDownloaded(fraction), []);
  const handleFail = useCallback(() => {
    setFailed(true);
    setReady(false);
  }, []);

  return (
    <div
      ref={robotRef}
      className={['robot', `robot--${size}`, className].filter(Boolean).join(' ')}
      data-crop={crop}
      data-renderer={use3d ? (ready ? '3d' : 'loading') : 'svg'}
      data-held={held}
      data-placed={placement !== null}
      aria-hidden="true"
    >
      <div
        className="robot__body"
        style={
          placement
            ? { position: 'fixed', left: placement.left, top: placement.top, width: placement.width, height: placement.height, right: 'auto', bottom: 'auto' }
            : undefined
        }
      >
        {quip && (
          <p key={quip} className="robot__quip" data-below={placement !== null && placement.top < 48}>
            {quip}
          </p>
        )}
        {use3d && (
          <div className="robot__layer robot__loader" data-visible={!ready} style={{ '--progress': loaded } as CSSProperties}>
            <span className="robot__ring" />
            <span className="robot__percent">{Math.round(loaded * 100)}%</span>
          </div>
        )}
        <div className="robot__layer" data-visible={showSvg}>
          <RobotFallback pose={shownPose} facing={shownFacing} crop={shownCrop} animated={!reducedMotion} followPointer={showSvg && !reducedMotion} />
        </div>
        {use3d && (
          <Robot3DBoundary onError={handleFail}>
            <Suspense fallback={null}>
              <div className="robot__layer" data-visible={ready}>
                <Robot3D
                  pose={shownPose}
                  facing={shownFacing}
                  crop={shownCrop}
                  onReady={handleReady}
                  onFail={handleFail}
                  onProgress={handleProgress}
                  stageRef={stageRef}
                />
              </div>
            </Suspense>
          </Robot3DBoundary>
        )}
      </div>
    </div>
  );
}
