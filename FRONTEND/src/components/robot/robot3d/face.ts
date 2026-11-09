/**
 * A cute face for a robot model whose face screen has eyes but no mouth: a mouth for each
 * mood and a shine on each eye. Everything sits on the screen's surface,
 * found by casting rays at it, so it follows the screen's curve. The model file itself is
 * unchanged; this is added each time it loads.
 */
import {
  CircleGeometry,
  Matrix3,
  Mesh,
  MeshBasicMaterial,
  Quaternion,
  Raycaster,
  SphereGeometry,
  TorusGeometry,
  Vector3,
  type BufferGeometry,
  type Material,
  type Object3D,
} from 'three';

export type MouthShape = 'smile' | 'grin' | 'oh';

const FORWARD = new Vector3(0, 0, 1);
const TONGUE = 0xff8a9e;

/** A point on the screen in head coordinates, and the way the screen faces there. */
function onScreen(head: Object3D, screen: Mesh, x: number, y: number) {
  const origin = head.localToWorld(new Vector3(x, y, 10));
  const direction = head.localToWorld(new Vector3(x, y, -10)).sub(origin).normalize();
  const hit = new Raycaster(origin, direction).intersectObject(screen, false)[0];
  if (!hit?.face) return undefined;
  const normal = hit.face.normal
    .clone()
    .applyMatrix3(new Matrix3().getNormalMatrix(screen.matrixWorld))
    .applyQuaternion(head.getWorldQuaternion(new Quaternion()).invert())
    .normalize();
  return { point: head.worldToLocal(hit.point.clone()), normal };
}

/** Lays flat geometry (facing +z) onto the screen at a point, just in front of it. */
function stick(head: Object3D, mesh: Mesh, at: { point: Vector3; normal: Vector3 }, lift: number): Mesh {
  mesh.quaternion.setFromUnitVectors(FORWARD, at.normal);
  mesh.position.copy(at.point).addScaledVector(at.normal, lift);
  head.add(mesh);
  return mesh;
}

function mesh(geometry: BufferGeometry, material: Material, name: string): Mesh {
  const m = new Mesh(geometry, material);
  m.name = name;
  return m;
}

/**
 * Adds the face to `head`, in the eyes' colour. Returns the mouths by shape (each hidden
 * except the smile), or undefined if there is no screen to draw on.
 */
export function addCuteFace(
  head: Object3D,
  screen: Mesh,
  eyeMeshes: Object3D[],
): Partial<Record<MouthShape, Object3D>> | undefined {
  const eye = eyeMeshes.find((e): e is Mesh => e instanceof Mesh);
  const feature = eye && !Array.isArray(eye.material) ? eye.material : undefined;
  if (!feature) return undefined;

  screen.geometry.computeBoundingBox();
  const area = screen.geometry.boundingBox!.clone().applyMatrix4(screen.matrix); // head coordinates
  const centre = area.getCenter(new Vector3());
  const size = area.getSize(new Vector3());
  const mouthAt = onScreen(head, screen, centre.x, centre.y - 0.25 * size.y);
  if (!mouthAt) return undefined;
  const r = 0.09 * size.y; // mouth size

  // Smile: the lower half of a thin ring.
  const smile = new TorusGeometry(r, r * 0.24, 8, 28, Math.PI).rotateZ(Math.PI).translate(0, r * 0.5, 0);
  // Grin: an open half-moon with a tongue.
  const grin = new Mesh(new CircleGeometry(r * 1.25, 28, Math.PI, Math.PI).translate(0, r * 0.45, 0), feature);
  const tongue = new Mesh(
    new CircleGeometry(r * 0.6, 20, 0, Math.PI).translate(0, -r * 0.5, 0.002),
    new MeshBasicMaterial({ color: TONGUE }),
  );
  grin.add(tongue);
  // A small "o" while thinking.
  const oh = new TorusGeometry(r * 0.5, r * 0.22, 8, 24);

  const mouths: Record<MouthShape, Object3D> = {
    smile: stick(head, mesh(smile, feature, 'MouthSmile'), mouthAt, 0.004),
    grin: stick(head, Object.assign(grin, { name: 'MouthGrin' }), mouthAt, 0.004),
    oh: stick(head, mesh(oh, feature, 'MouthOh'), mouthAt, 0.004),
  };
  for (const [shape, node] of Object.entries(mouths)) node.visible = shape === 'smile';

  // A big and a small shine on each eye. They're children of the eye, so they blink with
  // it; their scale undoes the eye's own stretch so they stay round.
  const shine = new MeshBasicMaterial({ color: 0xffffff });
  for (const e of eyeMeshes) {
    if (!(e instanceof Mesh)) continue;
    e.geometry.computeBoundingBox();
    const half = e.geometry.boundingBox!.max; // the eye's own half-size, before its scale
    const eyeRadius = half.x * e.scale.x; // as drawn, in its parent's units
    for (const [x, y, radius] of [[-0.34, 0.42, 0.3], [0.38, -0.32, 0.14]] as const) {
      const spot = mesh(new SphereGeometry(1, 12, 8), shine, 'EyeShine');
      spot.position.set(x * half.x, y * half.y, Math.sqrt(1 - x * x - y * y) * half.z);
      const size = radius * eyeRadius;
      spot.scale.set(size / e.scale.x, size / e.scale.y, size / e.scale.z);
      e.add(spot);
    }
  }
  return mouths;
}
