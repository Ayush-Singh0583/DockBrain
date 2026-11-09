import { BoxGeometry, Box3, Group, Mesh, MeshStandardMaterial, SphereGeometry, Vector3, type Object3D } from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
// The model the app loads by default (capabilities.ts), inlined by Vite as a data URL.
import bundledModel from '../../../../../GLB/dockbrain-companion.glb?inline';
import { fetchModel, rigFromGltf } from './glbRig';

async function bundledRobot() {
  const base64 = bundledModel.slice(bundledModel.indexOf(',') + 1);
  const bytes = Uint8Array.from(atob(base64), (c) => c.charCodeAt(0));
  return rigFromGltf(await new GLTFLoader().parseAsync(bytes.buffer, ''));
}

function meshesNamed(root: Object3D, pattern: RegExp): Mesh[] {
  const found: Mesh[] = [];
  root.traverse((node) => {
    if (node instanceof Mesh && pattern.test(node.name)) found.push(node);
  });
  return found;
}

describe('the bundled robot model', () => {
  it('has every part the poses move', async () => {
    const rig = await bundledRobot();
    expect(rig.head?.name).toBe('Head');
    expect(rig.torso?.name).toBe('Torso');
    expect(rig.armL?.name).toBe('ArmL');
    expect(rig.armR?.name).toBe('ArmR');
    expect(rig.eyes?.name).toBe('Eyes');
    expect(rig.eyeMeshes.map((n) => n.name)).toEqual(['EyeL', 'EyeR']);
    expect(rig.happyEyes.map((n) => n.name)).toEqual(['HappyEyeL', 'HappyEyeR']);
  });

  it('stands 2.4 units tall, centred, with its feet on the floor', async () => {
    const rig = await bundledRobot();
    const box = new Box3().setFromObject(rig.root);
    const size = box.getSize(new Vector3());
    const centre = box.getCenter(new Vector3());
    expect(size.y).toBeCloseTo(2.4, 3);
    expect(box.min.y).toBeCloseTo(0, 3);
    expect(centre.x).toBeCloseTo(0, 3);
    expect(centre.z).toBeCloseTo(0, 3);
  });

  it('pulses its chest light while thinking, but not its eyes', async () => {
    const rig = await bundledRobot();
    const lights = meshesNamed(rig.root, /^(Glow|ChestGlow|AntennaLight)/);
    expect(lights.length).toBeGreaterThan(0);
    for (const light of lights) expect(light.material).toBe(rig.glow);
    // The pulse changes emissive intensity, which shows only on a material that emits.
    expect(rig.glow?.emissive.getHex()).not.toBe(0);
    // The eyes share the light's material in the file; they must keep their own.
    for (const eye of [...rig.eyeMeshes, ...rig.happyEyes]) expect((eye as Mesh).material).not.toBe(rig.glow);
  });
});

describe('the bundled robot’s face', () => {
  it('gets a mouth for each mood, centred below the eyes on its face screen', async () => {
    const rig = await bundledRobot();
    rig.root.updateMatrixWorld(true);
    const eyes = rig.eyes!.getWorldPosition(new Vector3());
    const screen = new Box3().setFromObject(rig.root.getObjectByName('FaceScreen')!);
    expect(Object.keys(rig.mouths ?? {}).sort()).toEqual(['grin', 'oh', 'smile']);
    for (const mouth of Object.values(rig.mouths ?? {})) {
      expect(mouth.parent).toBe(rig.head);
      const at = mouth.getWorldPosition(new Vector3());
      expect(at.x).toBeCloseTo(eyes.x, 3);
      expect(at.y).toBeLessThan(eyes.y);
      expect(at.y).toBeGreaterThan(screen.min.y);
      expect(at.z).toBeGreaterThan(screen.max.z - 0.05); // on the screen's surface, not inside the head
    }
  });

  it('has no blush on its cheeks', async () => {
    const rig = await bundledRobot();
    expect(rig.root.getObjectByName('Cheek')).toBeUndefined();
  });

  it('gives each eye a shine that blinks with it', async () => {
    const rig = await bundledRobot();
    for (const eye of rig.eyeMeshes) expect(eye.children.length).toBeGreaterThan(0);
  });
});

describe('lights on any robot model', () => {
  it('glow even when the model’s light material doesn’t, and only the lights pulse', () => {
    // As in the earlier robot: two antenna lights sharing a plain teal with the eyes.
    const teal = new MeshStandardMaterial({ color: 0x10aa90 });
    const part = (name: string) => Object.assign(new Mesh(new SphereGeometry(), teal), { name });
    const eye = part('EyeL');
    const first = part('AntennaLight');
    const second = part('AntennaLight_1'); // how the loader renames a repeated name
    const scene = new Group();
    scene.add(eye, first, second);

    const rig = rigFromGltf({ scene, animations: [] });
    expect(first.material).toBe(rig.glow);
    expect(second.material).toBe(rig.glow);
    expect(rig.glow?.emissive.getHex()).not.toBe(0);
    expect(eye.material).toBe(teal);
  });
});

describe('fitting any robot model', () => {
  it('scales it to 2.4 units tall, centres it, and stands it on the floor', () => {
    // A model 6 units tall, built off to one side and floating above the origin.
    const scene = new Group();
    const body = new Mesh(new BoxGeometry(2, 6, 1));
    body.position.set(3, 10, -4);
    scene.add(body);
    const rig = rigFromGltf({ scene, animations: [] });
    const box = new Box3().setFromObject(rig.root);
    expect(box.getSize(new Vector3()).y).toBeCloseTo(2.4, 5);
    expect(box.min.y).toBeCloseTo(0, 5);
    expect(box.getCenter(new Vector3()).x).toBeCloseTo(0, 5);
    expect(box.getCenter(new Vector3()).z).toBeCloseTo(0, 5);
  });
});

describe('downloading the robot model', () => {
  function respondWith(chunks: Uint8Array[], length: number | null) {
    const body = new ReadableStream({
      start(controller) {
        chunks.forEach((chunk) => controller.enqueue(chunk));
        controller.close();
      },
    });
    const headers: Record<string, string> = length === null ? {} : { 'Content-Length': String(length) };
    return vi.fn(async () => new Response(body, { status: 200, headers }));
  }

  it('reports progress as the bytes arrive, and keeps the download for the next robot', async () => {
    const fetch = respondWith([new Uint8Array(30), new Uint8Array(70)], 100);
    vi.stubGlobal('fetch', fetch);
    const progress: number[] = [];
    const bytes = await fetchModel('/model-a.glb', (fraction) => progress.push(fraction));
    expect(bytes.byteLength).toBe(100);
    expect(progress).toEqual([0.3, 1]);

    const again: number[] = [];
    expect((await fetchModel('/model-a.glb', (fraction) => again.push(fraction))).byteLength).toBe(100);
    expect(fetch).toHaveBeenCalledTimes(1); // the second robot reuses the bytes
    expect(again).toEqual([1]);
  });

  it('still downloads when the size is unknown, and does not keep a failed download', async () => {
    vi.stubGlobal('fetch', respondWith([new Uint8Array(10)], null));
    expect((await fetchModel('/model-b.glb', () => {})).byteLength).toBe(10);

    const failing = vi.fn(async () => new Response('missing', { status: 404 }));
    vi.stubGlobal('fetch', failing);
    await expect(fetchModel('/model-c.glb', () => {})).rejects.toThrow();
    await expect(fetchModel('/model-c.glb', () => {})).rejects.toThrow();
    expect(failing).toHaveBeenCalledTimes(2); // tried again, not served from a cached failure
  });
});
