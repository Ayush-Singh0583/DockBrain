/**
 * Owns the WebGL renderer, camera, lights and render loop for one robot.
 *
 * Cost controls: no real-time shadows or post-processing, pixel ratio capped at 2,
 * at most 30 frames a second, and no rendering while the tab is hidden or the robot is
 * scrolled out of view.
 */
import {
  DirectionalLight,
  HemisphereLight,
  MathUtils,
  NeutralToneMapping,
  PerspectiveCamera,
  Raycaster,
  Scene,
  SRGBColorSpace,
  Vector2,
  Vector3,
  WebGLRenderer,
} from 'three';
import { pointerPoint, watchPointer } from '../pointer';
import type { RobotCrop, RobotFacing, RobotPose } from '../types';
import { RobotAnimator } from './animator';
import { buildProceduralRobot, type Rig } from './rig';

export interface StageOptions {
  crop: RobotCrop;
  glbUrl?: string;
  /** Called after the first frame is drawn. */
  onReady: () => void;
  /** How much of the robot model has downloaded (0–1). */
  onProgress?: (fraction: number) => void;
  /** Called if WebGL fails at any point (the caller switches to the SVG robot). */
  onFail: () => void;
}

export interface RobotStage {
  setPose(pose: RobotPose, facing: RobotFacing): void;
  /** Switches between the whole robot and head and shoulders without restarting. */
  setCrop(crop: RobotCrop): void;
  /** Whether a point on screen falls on the robot itself, not the empty space around it. */
  hitTest(clientX: number, clientY: number): boolean;
  /** Sideways drag speed (pixels per millisecond) while the robot is held. */
  nudge(speed: number): void;
  dispose(): void;
}

const FRAME = {
  full: { centerY: 1.2, height: 2.75, width: 2.7, lift: 0.45 },
  bust: { centerY: 1.88, height: 1.25, width: 1.75, lift: 0.2 }, // the head, with room to turn
} as const;
const MIN_FRAME_MS = 1000 / 30;
// Pointer distance from the head (in pixels) at which the gaze is about three-quarters turned.
const GAZE_REACH = 260;

export function createRobotStage(host: HTMLElement, options: StageOptions): RobotStage {
  // Throws if a WebGL context can't be created; the React wrapper reports that as a failure.
  const renderer = new WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'low-power' });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.outputColorSpace = SRGBColorSpace;
  renderer.toneMapping = NeutralToneMapping;
  renderer.toneMappingExposure = 1.02;
  renderer.setClearColor(0x000000, 0);
  const canvas = renderer.domElement;
  canvas.style.display = 'block';
  canvas.style.width = '100%';
  canvas.style.height = '100%';
  host.appendChild(canvas);

  const scene = new Scene();
  scene.add(new HemisphereLight(0xffffff, 0xd2cabd, 1.7));
  const key = new DirectionalLight(0xfff4e6, 2.1);
  key.position.set(-2.5, 4, 5);
  const rim = new DirectionalLight(0xe4ecff, 1.3);
  rim.position.set(3, 2.5, -3);
  const fill = new DirectionalLight(0xffffff, 0.45);
  fill.position.set(3, 1, 4);
  scene.add(key, rim, fill);

  const camera = new PerspectiveCamera(26, 1, 0.1, 50);
  let crop = options.crop;

  let rig: Rig = buildProceduralRobot();
  let animator = new RobotAnimator(rig);
  scene.add(rig.root);
  const showShadow = () => {
    if (rig.shadow) rig.shadow.visible = crop !== 'bust';
  };
  showShadow();
  const stopWatchingPointer = watchPointer();
  const head = new Vector3();
  const raycaster = new Raycaster();
  const ndc = new Vector2();

  let pose: RobotPose = 'idle';
  let facing: RobotFacing = 'front';
  let disposed = false;
  // While a model loads, draw nothing, so the SVG robot stays until the model can replace
  // it, rather than the built-in 3D robot appearing and then being swapped.
  let modelPending = Boolean(options.glbUrl);

  if (options.glbUrl) {
    import('./glbRig')
      .then(({ loadGlbRig }) => loadGlbRig(options.glbUrl!, options.onProgress))
      .then((loaded) => {
        if (disposed) return loaded.dispose();
        scene.remove(rig.root);
        rig.dispose();
        animator.dispose();
        rig = loaded;
        animator = new RobotAnimator(rig);
        animator.setPose(pose, facing);
        scene.add(rig.root);
        showShadow();
      })
      .catch((error: unknown) => {
        // Keep the procedural robot. The message names the asset only, never user data.
        console.warn(`DockBrain: couldn't load robot model ${options.glbUrl}; using the built-in robot.`, error);
      })
      .finally(() => {
        modelPending = false;
      });
  }

  const fit = () => {
    const frame = FRAME[crop];
    const width = host.clientWidth || 1;
    const height = host.clientHeight || 1;
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    const tan = Math.tan(MathUtils.degToRad(camera.fov / 2));
    const distance = Math.max(frame.height / (2 * tan), frame.width / (2 * tan * camera.aspect));
    camera.position.set(0, frame.centerY + frame.lift, distance);
    camera.lookAt(0, frame.centerY, 0);
    camera.updateProjectionMatrix();
  };
  fit();

  // Tell the animator where the pointer is relative to the head, as drawn on screen.
  const look = () => {
    const point = pointerPoint();
    if (!point) return animator.setLook(null);
    const rect = canvas.getBoundingClientRect();
    if (rig.head) rig.head.getWorldPosition(head);
    else head.set(0, 1.9, 0);
    head.project(camera);
    const headX = rect.left + ((head.x + 1) / 2) * rect.width;
    const headY = rect.top + ((1 - head.y) / 2) * rect.height;
    animator.setLook({ x: Math.tanh((point.x - headX) / GAZE_REACH), y: Math.tanh((point.y - headY) / GAZE_REACH) });
  };

  let last = 0;
  let readySent = false;
  const tick = (now: number) => {
    if (modelPending || (last && now - last < MIN_FRAME_MS)) return;
    const dt = last ? Math.min((now - last) / 1000, 0.1) : 0;
    last = now;
    look();
    animator.update(dt);
    renderer.render(scene, camera);
    if (!readySent) {
      readySent = true;
      options.onReady();
    }
  };

  let onScreen = true;
  let running = false;
  const updateLoop = () => {
    const shouldRun = !disposed && onScreen && document.visibilityState !== 'hidden';
    if (shouldRun === running) return;
    running = shouldRun;
    last = 0;
    renderer.setAnimationLoop(shouldRun ? tick : null);
  };

  const resizeObserver = new ResizeObserver(fit);
  resizeObserver.observe(host);
  const intersectionObserver = new IntersectionObserver(([entry]) => {
    onScreen = entry?.isIntersecting ?? true;
    updateLoop();
  });
  intersectionObserver.observe(host);
  document.addEventListener('visibilitychange', updateLoop);

  const onContextLost = (event: Event) => {
    event.preventDefault();
    options.onFail();
  };
  canvas.addEventListener('webglcontextlost', onContextLost);

  updateLoop();

  return {
    setPose(nextPose, nextFacing) {
      pose = nextPose;
      facing = nextFacing;
      animator.setPose(nextPose, nextFacing);
    },
    setCrop(nextCrop) {
      if (nextCrop === crop) return;
      crop = nextCrop;
      showShadow();
      fit();
    },
    hitTest(clientX, clientY) {
      if (modelPending) return false;
      const rect = canvas.getBoundingClientRect();
      if (clientX < rect.left || clientX > rect.right || clientY < rect.top || clientY > rect.bottom) return false;
      ndc.set(((clientX - rect.left) / rect.width) * 2 - 1, -((clientY - rect.top) / rect.height) * 2 + 1);
      raycaster.setFromCamera(ndc, camera);
      return raycaster.intersectObject(rig.root, true).some((hit) => hit.object.visible && hit.object !== rig.shadow);
    },
    nudge(speed) {
      animator.nudge(speed);
    },
    dispose() {
      disposed = true;
      stopWatchingPointer();
      renderer.setAnimationLoop(null);
      resizeObserver.disconnect();
      intersectionObserver.disconnect();
      document.removeEventListener('visibilitychange', updateLoop);
      canvas.removeEventListener('webglcontextlost', onContextLost);
      animator.dispose();
      rig.dispose();
      renderer.dispose();
      renderer.forceContextLoss();
      canvas.remove();
    },
  };
}
