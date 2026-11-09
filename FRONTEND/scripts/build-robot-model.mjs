/**
 * Builds the DockBrain companion robot from simple shapes and saves it as a GLB:
 *
 *   node scripts/build-robot-model.mjs [output]   (default ../GLB/dockbrain-companion.glb)
 *
 * The look follows the user's reference picture (2026-11-08), with their changes: an
 * elliptical head without ears; a dark oval face screen with glowing cyan eyes and edge
 * arcs; a big, plain white, floating round body whose radius is the screen's width, with a
 * chest light; and detached egg-shaped hands. Part names are the ones the app's poses move
 * (HANDOFF.md, "Replacing the robot with a GLB"): Torso, ArmL, ArmR (pivot at the
 * shoulder), Head (pivot at the neck), Eyes, EyeL, EyeR, HappyEyeL, HappyEyeR, FaceScreen
 * and ChestGlow. The app adds the mouth, eye shines and cheeks when it loads the model
 * (src/components/robot/robot3d/face.ts).
 */
import { writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  BufferGeometry,
  CatmullRomCurve3,
  Color,
  CylinderGeometry,
  Float32BufferAttribute,
  Group,
  LatheGeometry,
  Mesh,
  MeshStandardMaterial,
  Quaternion,
  Scene,
  SphereGeometry,
  TorusGeometry,
  TubeGeometry,
  Vector2,
  Vector3,
} from 'three';
import { GLTFExporter } from 'three/examples/jsm/exporters/GLTFExporter.js';

// The exporter reads its output through FileReader, which Node lacks; this is the part it uses.
globalThis.FileReader ??= class {
  readAsArrayBuffer(blob) {
    blob.arrayBuffer().then((buffer) => {
      this.result = buffer;
      this.onloadend?.();
    });
  }
};

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');

// The face screen's half-width. The body's radius was set to the screen's full width (its
// major diameter), as the user asked on 2026-11-08; the head was then scaled up to suit the
// bigger body (HEAD_SCALE), so the screen as drawn is now wider than that.
const FACE_RX = 0.57;
const HEAD_SCALE = 1.39; // the head as wide as the body
const output = resolve(process.argv[2] ?? resolve(root, '../GLB/dockbrain-companion.glb'));

// ------------------------------------------------------------------ materials

const material = (name, options) => Object.assign(new MeshStandardMaterial(options), { name });
const shell = material('Shell white', { color: new Color('#f2f4f7'), roughness: 0.3, metalness: 0 });
const paleBlue = material('Pale blue', { color: new Color('#cfe2fb'), roughness: 0.35, metalness: 0 });
const screen = material('Face screen', { color: new Color('#22252b'), roughness: 0.14, metalness: 0.2 });
const glow = material('Glow cyan', { color: new Color('#a6f4ff'), emissive: new Color('#46dcff'), emissiveIntensity: 1, roughness: 0.3 });
const bracket = material('Bracket cyan', { color: new Color('#2b8ea6'), emissive: new Color('#46dcff'), emissiveIntensity: 0.55, roughness: 0.4 });
const seam = material('Seam', { color: new Color('#c9ced6'), roughness: 0.5, metalness: 0 });

function part(name, geometry, mat, parent, at = [0, 0, 0]) {
  const mesh = new Mesh(geometry, mat);
  mesh.name = name;
  mesh.position.set(...at);
  parent.add(mesh);
  return mesh;
}

function group(name, parent, at = [0, 0, 0]) {
  const g = new Group();
  g.name = name;
  g.position.set(...at);
  parent.add(g);
  return g;
}

// ------------------------------------------------------------------ body

const robot = new Group();
robot.name = 'DockBrainCompanion';

// Round body: a sphere (lean 0; a positive lean would widen it above the middle into an
// egg), floating (no legs). Profile: [radius, height], from the bottom to the top.
const BODY = { height: 4 * FACE_RX, radius: 2 * FACE_RX, lean: 0 };
const GROWTH = BODY.radius / 0.66; // how much bigger than the first round body; parts on it grow less
const PROFILE = Array.from({ length: 33 }, (_, i) => {
  const s = -1 + i / 16; // -1 at the bottom, 1 at the top
  const radius = BODY.radius * Math.sqrt(Math.max(1 - s * s, 0)) * (1 + BODY.lean * s);
  return [Math.max(radius, 0.001), ((s + 1) / 2) * BODY.height];
});
const radiusAt = (y) => {
  for (let i = 1; i < PROFILE.length; i++) {
    const [r0, y0] = PROFILE[i - 1];
    const [r1, y1] = PROFILE[i];
    if (y <= y1) return r0 + ((r1 - r0) * (y - y0)) / (y1 - y0);
  }
  return 0;
};
/** A point on the body's surface at height y and sideways offset x, and its outward normal. */
function onBody(x, y, lift = 0) {
  const r = radiusAt(y) + lift;
  const slope = (radiusAt(y + 0.01) - radiusAt(y - 0.01)) / 0.02;
  const z = Math.sqrt(Math.max(r * r - x * x, 0));
  const normal = new Vector3(x / r, -slope, z / r).normalize();
  return { point: new Vector3(x, y, z), normal };
}
function faceOutward(mesh, normal, axis = new Vector3(0, 0, 1)) {
  mesh.quaternion.copy(new Quaternion().setFromUnitVectors(axis, normal));
}

const torso = group('Torso', robot);
part('BodyShell', new LatheGeometry(PROFILE.map(([r, y]) => new Vector2(r, y)), 64), shell, torso);

// Chest light with a pale ring, on the body to the viewer's right.
const CHEST = 0.095 * Math.sqrt(GROWTH);
const chest = onBody(0.24 * GROWTH, 0.74 * BODY.height, 0.012);
const light = part('ChestGlow', new CylinderGeometry(CHEST, CHEST, 0.04, 40), glow, torso, chest.point.toArray());
faceOutward(light, chest.normal, new Vector3(0, 1, 0));
const ring = part('ChestRing', new TorusGeometry(CHEST * 1.1, 0.02 * Math.sqrt(GROWTH), 12, 40), paleBlue, torso, chest.point.toArray());
faceOutward(ring, chest.normal);

// A faint seam near the bottom.
const SEAM = 0.14 * BODY.height;
const seamRing = part('BodySeam', new TorusGeometry(radiusAt(SEAM) + 0.002, 0.006, 8, 64), seam, torso, [0, SEAM, 0]);
seamRing.rotation.x = Math.PI / 2;

// Detached arms: plain white, flat egg-shaped hands, wide at the shoulder and narrowing to
// the tip, angled outward, floating just clear of the body.
function eggGeometry(halfLength, width) {
  const points = [];
  for (let i = 0; i <= 32; i++) {
    const s = -1 + (2 * i) / 32; // -1 at the narrow tip (away from the body), 1 at the wide end
    const radius = width * Math.sqrt(Math.max(1 - s * s, 0)) * (1 + 0.22 * s);
    points.push(new Vector2(Math.max(radius, 0.001), s * halfLength));
  }
  return new LatheGeometry(points, 40);
}
const SHOULDER = 0.78 * BODY.height;
for (const [name, side] of [['ArmL', -1], ['ArmR', 1]]) {
  // Far enough out that a raised hand waves beside the big head rather than through it.
  const arm = group(name, torso, [(radiusAt(SHOULDER) + 0.22) * side, SHOULDER, 0]);
  const size = GROWTH; // hands grow with the body, keeping their earlier proportion
  const hand = part(`${name}Hand`, eggGeometry(0.3 * size, 0.165 * size).scale(1, 1, 0.58), shell, arm, [0.12 * size * side, -0.24 * size, 0]);
  hand.rotation.z = 0.4 * side;
}

// ------------------------------------------------------------------ head

const NECK = BODY.height - 0.01; // the head rests on top of the body
// An elliptical head: a smooth ellipsoid, wider than it is tall.
const HEAD = { rx: 0.82, ry: 0.62, rz: 0.6, y: 0.62 };
const head = group('Head', robot, [0, NECK, 0]);
head.scale.setScalar(HEAD_SCALE); // grows from the neck, so it still rests on the body
part('HeadShell', new SphereGeometry(1, 72, 48).scale(HEAD.rx, HEAD.ry, HEAD.rz), shell, head, [0, HEAD.y, 0]);

// Dark oval face screen: a patch that follows the head's curve, just proud of it.
const SCREEN = { rx: FACE_RX, ry: 0.38, y: HEAD.y + 0.02, lift: 0.012 };
const FACE = { rx: HEAD.rx + SCREEN.lift, ry: HEAD.ry + SCREEN.lift, rz: HEAD.rz + SCREEN.lift };
/** The screen surface's depth (head coordinates) at a point on the face. */
const faceZ = (x, y) => {
  const fx = x / FACE.rx;
  const fy = (y - HEAD.y) / FACE.ry;
  return FACE.rz * Math.sqrt(Math.max(1 - fx * fx - fy * fy, 0));
};
/** The way the screen faces at a point on it. */
const faceNormal = (x, y) => new Vector3(x / FACE.rx ** 2, (y - HEAD.y) / FACE.ry ** 2, faceZ(x, y) / FACE.rz ** 2).normalize();

function screenPatch(rings = 24, segments = 96) {
  const positions = [0, SCREEN.y, faceZ(0, SCREEN.y)];
  const indices = [];
  for (let r = 1; r <= rings; r++) {
    for (let k = 0; k < segments; k++) {
      const a = (k / segments) * Math.PI * 2;
      const x = (r / rings) * SCREEN.rx * Math.cos(a);
      const y = SCREEN.y + (r / rings) * SCREEN.ry * Math.sin(a);
      positions.push(x, y, faceZ(x, y));
    }
  }
  for (let k = 0; k < segments; k++) indices.push(0, 1 + k, 1 + ((k + 1) % segments));
  for (let r = 1; r < rings; r++) {
    const inner = 1 + (r - 1) * segments;
    const outer = 1 + r * segments;
    for (let k = 0; k < segments; k++) {
      const next = (k + 1) % segments;
      indices.push(inner + k, outer + k, outer + next, inner + k, outer + next, inner + next);
    }
  }
  const geometry = new BufferGeometry();
  geometry.setAttribute('position', new Float32BufferAttribute(positions, 3));
  geometry.setIndex(indices);
  geometry.computeVertexNormals();
  return geometry;
}
part('FaceScreen', screenPatch(), screen, head);

// Thin glowing arcs at the screen's four diagonals, following its oval edge and the head's curve.
const RING = 0.9; // how far out the arcs sit, as a fraction of the screen's radii (clear of the cheeks)
for (const centre of [45, 135, 225, 315]) {
  const points = [];
  for (let degrees = centre - 13; degrees <= centre + 13; degrees += 2) {
    const a = (degrees * Math.PI) / 180;
    const x = RING * SCREEN.rx * Math.cos(a);
    const y = SCREEN.y + RING * SCREEN.ry * Math.sin(a);
    points.push(new Vector3(x, y, faceZ(x, y)).addScaledVector(faceNormal(x, y), 0.006));
  }
  part('Bracket', new TubeGeometry(new CatmullRomCurve3(points), 24, 0.009, 8, false), bracket, head);
}

// Eyes: glowing ovals, and happy arcs (shown instead when it's pleased or waving), each
// laid on the curved screen and facing out from it.
const EYE_Y = SCREEN.y + 0.03;
const eyes = group('Eyes', head, [0, EYE_Y, 0]);
for (const [suffix, side] of [['L', -1], ['R', 1]]) {
  const x = 0.22 * side;
  const at = new Vector3(x, 0, faceZ(x, EYE_Y)).addScaledVector(faceNormal(x, EYE_Y), 0.004);
  const facing = new Quaternion().setFromUnitVectors(new Vector3(0, 0, 1), faceNormal(x, EYE_Y));
  const eye = part(`Eye${suffix}`, new SphereGeometry(1, 32, 20), glow, eyes, at.toArray());
  eye.scale.set(0.085, 0.12, 0.025);
  eye.quaternion.copy(facing);
  const happy = part(`HappyEye${suffix}`, new TorusGeometry(0.1, 0.027, 12, 28, Math.PI).translate(0, -0.04, 0), glow, eyes, at.toArray());
  happy.quaternion.copy(facing);
}

// ------------------------------------------------------------------ export

const scene = new Scene();
scene.add(robot);
const glb = await new GLTFExporter().parseAsync(scene, { binary: true });
writeFileSync(output, Buffer.from(glb));

let triangles = 0;
robot.traverse((node) => {
  if (node.isMesh) triangles += (node.geometry.index?.count ?? node.geometry.attributes.position.count) / 3;
});
console.log(`Saved ${output}: ${(glb.byteLength / 1024).toFixed(0)} KB, ${Math.round(triangles)} triangles.`);
