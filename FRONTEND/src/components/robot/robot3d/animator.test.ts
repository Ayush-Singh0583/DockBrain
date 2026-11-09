import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import bundledModel from '../../../../../GLB/dockbrain-companion.glb?inline';
import type { RobotPose } from '../types';
import { RobotAnimator } from './animator';
import { rigFromGltf } from './glbRig';

async function bundledRobot() {
  const bytes = Uint8Array.from(atob(bundledModel.slice(bundledModel.indexOf(',') + 1)), (c) => c.charCodeAt(0));
  return rigFromGltf(await new GLTFLoader().parseAsync(bytes.buffer, ''));
}

/** Which mouth shows, and whether the eyes are open or happy, after `seconds` in a pose. */
async function faceIn(pose: RobotPose, seconds = 0.5) {
  const rig = await bundledRobot();
  const animator = new RobotAnimator(rig);
  animator.setPose(pose, 'front');
  for (let t = 0; t < seconds; t += 0.05) animator.update(0.05);
  const shown = Object.entries(rig.mouths ?? {}).filter(([, mouth]) => mouth.visible).map(([shape]) => shape);
  return { mouth: shown, eyes: rig.happyEyes.every((e) => e.visible) ? 'happy' : 'open' };
}

describe('the robot’s expressions', () => {
  it('smiles when idle', async () => {
    expect(await faceIn('idle')).toEqual({ mouth: ['smile'], eyes: 'open' });
  });

  it('grins with happy eyes while waving hello, then smiles', async () => {
    expect(await faceIn('greet', 1)).toEqual({ mouth: ['grin'], eyes: 'happy' });
    expect(await faceIn('greet', 3.5)).toEqual({ mouth: ['smile'], eyes: 'open' });
  });

  it('makes a small “o” while thinking', async () => {
    expect(await faceIn('think')).toEqual({ mouth: ['oh'], eyes: 'open' });
  });

  it('grins when something works', async () => {
    expect(await faceIn('success')).toEqual({ mouth: ['grin'], eyes: 'happy' });
  });

  it('closes its eyes and grins while flying', async () => {
    expect(await faceIn('flying')).toEqual({ mouth: ['grin'], eyes: 'happy' });
  });
});
