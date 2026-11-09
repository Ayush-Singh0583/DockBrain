/**
 * The robot's articulated parts, independent of where they came from. The procedural
 * builder below and the GLB loader (glbRig.ts) both produce a `Rig`, and the animator
 * drives whatever joints are present.
 */
import type { MouthShape } from './face';
import {
  AnimationClip,
  BackSide,
  CanvasTexture,
  CapsuleGeometry,
  CylinderGeometry,
  Group,
  LatheGeometry,
  Mesh,
  MeshBasicMaterial,
  MeshStandardMaterial,
  Object3D,
  PlaneGeometry,
  SphereGeometry,
  SplineCurve,
  TorusGeometry,
  Vector2,
  type BufferGeometry,
  type Material,
} from 'three';

export interface Rig {
  /** Whole robot: turned for facing, lifted for hops. Feet at y = 0, about 2.4 units tall. */
  root: Object3D;
  /** Moves gently up and down while breathing. */
  torso?: Object3D;
  /** Scaled slightly while breathing. */
  body?: Object3D;
  head?: Object3D;
  /** Viewer's left and right arms; rotate around the shoulder. */
  armL?: Object3D;
  armR?: Object3D;
  /** Moved a little to change where the robot looks. */
  eyes?: Object3D;
  /** Squashed vertically to blink. */
  eyeMeshes: Object3D[];
  /** Shown instead of the open eyes in the success pose and while waving hello. */
  happyEyes: Object3D[];
  /** Mouths for each mood, if the face has several; the one for the current pose shows. */
  mouths?: Partial<Record<MouthShape, Object3D>>;
  /** Thought light; its glow pulses while thinking. */
  glow?: MeshStandardMaterial;
  shadow?: Object3D;
  /** Animation clips supplied by a GLB, named after poses (idle, greet, point, think, success). */
  clips: AnimationClip[];
  dispose(): void;
}

export const ROBOT_COLORS = {
  shell: 0xfdfcf9,
  detail: 0xe7e2d9,
  ink: 0x1c1b19,
  accent: 0x2f7a6f,
  line: 0xc4bcae,
};

/** An inverted-hull outline: gives the white robot a soft drawn edge on a white page. */
function outlineMaterial(thickness: number): MeshBasicMaterial {
  const material = new MeshBasicMaterial({ color: ROBOT_COLORS.line, side: BackSide });
  material.onBeforeCompile = (shader) => {
    shader.vertexShader = shader.vertexShader.replace(
      '#include <begin_vertex>',
      `#include <begin_vertex>\ntransformed += normal * ${thickness.toFixed(4)};`,
    );
  };
  return material;
}

function shadowTexture(): CanvasTexture {
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = 128;
  const ctx = canvas.getContext('2d')!;
  const gradient = ctx.createRadialGradient(64, 64, 4, 64, 64, 64);
  gradient.addColorStop(0, 'rgba(28,27,25,0.28)');
  gradient.addColorStop(1, 'rgba(28,27,25,0)');
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, 128, 128);
  return new CanvasTexture(canvas);
}

export function buildProceduralRobot(): Rig {
  const geometries: BufferGeometry[] = [];
  const materials: Material[] = [];
  const track = <T extends BufferGeometry>(g: T) => (geometries.push(g), g);
  const trackM = <T extends Material>(m: T) => (materials.push(m), m);

  const shell = trackM(new MeshStandardMaterial({ color: ROBOT_COLORS.shell, roughness: 0.42, metalness: 0 }));
  const detail = trackM(new MeshStandardMaterial({ color: ROBOT_COLORS.detail, roughness: 0.6 }));
  const ink = trackM(new MeshStandardMaterial({ color: ROBOT_COLORS.ink, roughness: 0.32 }));
  const glow = trackM(
    new MeshStandardMaterial({ color: ROBOT_COLORS.accent, emissive: ROBOT_COLORS.accent, emissiveIntensity: 0.35, roughness: 0.4 }),
  );
  const outline = trackM(outlineMaterial(0.016));

  const part = (geometry: BufferGeometry, material: Material, withOutline = false) => {
    const mesh = new Mesh(track(geometry), material);
    if (withOutline) mesh.add(new Mesh(geometry, outline));
    return mesh;
  };

  const root = new Group();
  root.name = 'DockBrainRobot';

  // Legs: short rounded stubs.
  for (const x of [-0.25, 0.25]) {
    const leg = part(new CapsuleGeometry(0.16, 0.12, 8, 20), shell, true);
    leg.position.set(x, 0.22, 0);
    root.add(leg);
  }

  const torso = new Group();
  torso.position.y = 0.18;
  root.add(torso);

  // Body: a soft pear shape, widest near the bottom.
  const profile = new SplineCurve([
    new Vector2(0.001, 0),
    new Vector2(0.36, 0.015),
    new Vector2(0.55, 0.11),
    new Vector2(0.64, 0.3),
    new Vector2(0.655, 0.5),
    new Vector2(0.6, 0.74),
    new Vector2(0.5, 0.93),
    new Vector2(0.36, 1.06),
    new Vector2(0.2, 1.13),
    new Vector2(0.001, 1.15),
  ]).getPoints(48);
  const body = part(new LatheGeometry(profile, 64), shell, true);
  torso.add(body);

  // Chest badge with a small accent light: DockBrain's mark.
  const badge = part(new CylinderGeometry(0.11, 0.11, 0.03, 40), detail);
  badge.rotation.x = Math.PI / 2 - 0.12;
  badge.position.set(0, 0.56, 0.632);
  const badgeLight = part(new CylinderGeometry(0.042, 0.042, 0.02, 32), glow);
  badgeLight.position.y = 0.02;
  badge.add(badgeLight);
  torso.add(badge);

  // Arms pivot at the shoulder and hang slightly outward.
  const makeArm = (side: -1 | 1) => {
    const pivot = new Group();
    pivot.position.set(0.55 * side, 0.84, 0);
    const arm = part(new CapsuleGeometry(0.145, 0.3, 8, 20), shell, true);
    arm.position.set(0.05 * side, -0.27, 0);
    pivot.add(arm);
    pivot.rotation.z = 0.12 * side;
    torso.add(pivot);
    return pivot;
  };
  const armL = makeArm(-1);
  const armR = makeArm(1);

  // Head pivots at the neck so tilts look natural.
  const head = new Group();
  head.position.y = 1.1;
  torso.add(head);
  const skull = part(new SphereGeometry(0.5, 48, 32), shell, true);
  skull.scale.set(1.06, 0.9, 0.95);
  skull.position.y = 0.42;
  head.add(skull);

  for (const side of [-1, 1]) {
    const ear = part(new CylinderGeometry(0.12, 0.12, 0.1, 32), detail, true);
    ear.rotation.z = Math.PI / 2;
    ear.position.set(0.52 * side, 0.42, 0);
    head.add(ear);
  }

  const stalk = part(new CylinderGeometry(0.016, 0.016, 0.14, 12), detail);
  stalk.position.set(0, 0.88, 0);
  head.add(stalk);
  const bulb = part(new SphereGeometry(0.046, 20, 14), glow);
  bulb.position.set(0, 0.97, 0);
  head.add(bulb);

  const eyes = new Group();
  eyes.position.y = 0.42;
  head.add(eyes);
  const eyeMeshes: Object3D[] = [];
  const happyEyes: Object3D[] = [];
  for (const side of [-1, 1]) {
    const eye = part(new SphereGeometry(0.058, 20, 14), ink);
    eye.scale.set(1, 1.18, 0.5);
    eye.position.set(0.165 * side, 0.03, 0.444);
    eye.rotation.y = 0.36 * side;
    eyes.add(eye);
    eyeMeshes.push(eye);

    const happy = part(new TorusGeometry(0.055, 0.014, 8, 24, Math.PI), ink);
    happy.position.set(0.165 * side, 0.01, 0.448);
    happy.rotation.set(-0.05, 0.36 * side, 0);
    happy.visible = false;
    eyes.add(happy);
    happyEyes.push(happy);
  }

  const mouth = part(new TorusGeometry(0.07, 0.012, 8, 24, Math.PI * 0.8), ink);
  mouth.rotation.set(-0.27, 0, Math.PI + Math.PI * 0.1);
  mouth.position.set(0, 0.42 - 0.12, 0.452);
  head.add(mouth);

  // Soft contact shadow (a textured plane; no real-time shadows needed).
  const shadowMap = shadowTexture();
  const shadowMat = trackM(new MeshBasicMaterial({ map: shadowMap, transparent: true, depthWrite: false }));
  const shadow = new Mesh(track(new PlaneGeometry(1.7, 0.8)), shadowMat);
  shadow.rotation.x = -Math.PI / 2;
  shadow.position.y = 0.005;
  root.add(shadow);

  return {
    root,
    torso,
    body,
    head,
    armL,
    armR,
    eyes,
    eyeMeshes,
    happyEyes,
    glow,
    shadow,
    clips: [],
    dispose() {
      geometries.forEach((g) => g.dispose());
      materials.forEach((m) => m.dispose());
      shadowMap.dispose();
    },
  };
}
