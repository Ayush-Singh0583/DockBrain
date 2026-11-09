/**
 * Loads a robot model (GLB/GLTF) and maps it onto the same `Rig` the procedural robot
 * uses. See public/models/README.md.
 *
 * Node names are matched case-insensitively, ignoring "_", "-", "." and spaces:
 *   Head, ArmL, ArmR, Torso (or Body), Eyes, EyeL, EyeR, HappyEyeL, HappyEyeR,
 *   and lights named Glow, ChestGlow or AntennaLight
 * Missing nodes are fine: the matching motion is skipped. Clips named idle, greet,
 * point, think or success play for that pose instead of the built-in motion.
 */
import {
  Box3,
  Mesh,
  MeshStandardMaterial,
  Vector3,
  type AnimationClip,
  type Material,
  type Object3D,
} from 'three';
import { addCuteFace } from './face';
import type { Rig } from './rig';

const TARGET_HEIGHT = 2.4;
// Lights that pulse while thinking. The loader numbers repeated names ("AntennaLight_1").
const LIGHT_NAME = /^(?:glow|chestglow|antennalight)\d*$/;

function normalise(name: string): string {
  return name.toLowerCase().replace(/[\s_.-]/g, '');
}

// Model files already downloaded, by URL, so a robot on the next screen appears at once.
const downloads = new Map<string, Promise<ArrayBuffer>>();

/**
 * The model's bytes, reporting the downloaded fraction (0–1) as they arrive when the server
 * gives a size. Kept for later robots; a failed download isn't kept, so it's tried again.
 */
export function fetchModel(url: string, onProgress: (fraction: number) => void): Promise<ArrayBuffer> {
  const kept = downloads.get(url);
  if (kept) return kept.then((bytes) => (onProgress(1), bytes));
  const download = (async () => {
    const response = await fetch(url);
    if (!response.ok || !response.body) throw new Error(`The robot model couldn't be downloaded (${response.status}).`);
    const total = Number(response.headers.get('Content-Length')) || 0;
    const reader = response.body.getReader();
    const parts: Uint8Array[] = [];
    let received = 0;
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      parts.push(value);
      received += value.byteLength;
      if (total) onProgress(Math.min(received / total, 1));
    }
    if (!total) onProgress(1);
    const bytes = new Uint8Array(received);
    let offset = 0;
    for (const part of parts) {
      bytes.set(part, offset);
      offset += part.byteLength;
    }
    return bytes.buffer;
  })();
  downloads.set(url, download);
  download.catch(() => downloads.delete(url));
  return download;
}

export async function loadGlbRig(url: string, onProgress: (fraction: number) => void = () => {}): Promise<Rig> {
  const [{ GLTFLoader }, { LoaderUtils }, bytes] = await Promise.all([
    import('three/examples/jsm/loaders/GLTFLoader.js'),
    import('three'),
    fetchModel(url, onProgress),
  ]);
  return rigFromGltf(await new GLTFLoader().parseAsync(bytes, LoaderUtils.extractUrlBase(url)));
}

/**
 * The lights' material, copied so that only the lights pulse: a model may share it with
 * other parts (the bundled robot's eyes use the same teal). A light that doesn't emit is
 * given its own colour as emissive, or the pulse wouldn't show.
 */
function glowMaterial(model: Object3D): MeshStandardMaterial | undefined {
  const lights: Mesh[] = [];
  model.traverse((node) => {
    if (node instanceof Mesh && LIGHT_NAME.test(normalise(node.name))) lights.push(node);
  });
  const shared = lights.map((light) => light.material).find((m) => m instanceof MeshStandardMaterial);
  if (!shared) return undefined;
  const glow = shared.clone();
  if (glow.emissive.getHex() === 0) glow.emissive.copy(glow.color);
  for (const light of lights) if (light.material === shared) light.material = glow;
  return glow;
}

export function rigFromGltf(gltf: { scene: Object3D; animations: AnimationClip[] }): Rig {
  const model = gltf.scene;

  const nodes = new Map<string, Object3D>();
  model.traverse((node) => {
    if (node.name && !nodes.has(normalise(node.name))) nodes.set(normalise(node.name), node);
  });
  const find = (...names: string[]) => names.map((n) => nodes.get(normalise(n))).find(Boolean);

  const head = find('Head');
  const eyeMeshes = [find('EyeL'), find('EyeR')].filter((n): n is Object3D => Boolean(n));
  // A face screen with no mouth gets a drawn-on face: mouths for each mood, eye shines, cheeks.
  const screen = find('FaceScreen');
  model.updateMatrixWorld(true);
  const mouths =
    head && screen instanceof Mesh && !find('Mouth') ? addCuteFace(head, screen, eyeMeshes) : undefined;

  // Then fit, face included, to the procedural robot's size: feet on the floor, centred, ~2.4 units tall.
  const box = new Box3().setFromObject(model);
  const size = box.getSize(new Vector3());
  if (size.y > 0) model.scale.multiplyScalar(TARGET_HEIGHT / size.y);
  box.setFromObject(model);
  const centre = box.getCenter(new Vector3());
  model.position.x -= centre.x;
  model.position.z -= centre.z;
  model.position.y -= box.min.y;

  return {
    root: model,
    torso: find('Torso', 'Body'),
    body: undefined, // breathing scale is skipped for GLBs; the torso bob still plays
    head,
    armL: find('ArmL', 'LeftArm', 'Arm.L'),
    armR: find('ArmR', 'RightArm', 'Arm.R'),
    eyes: find('Eyes'),
    eyeMeshes,
    happyEyes: [find('HappyEyeL'), find('HappyEyeR')].filter((n): n is Object3D => Boolean(n)),
    mouths,
    glow: glowMaterial(model),
    clips: gltf.animations,
    dispose() {
      model.traverse((node) => {
        if (node instanceof Mesh) {
          node.geometry.dispose();
          const materials: Material[] = Array.isArray(node.material) ? node.material : [node.material];
          materials.forEach((m) => m.dispose());
        }
      });
    },
  };
}
