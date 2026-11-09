/**
 * Pose motion for any `Rig`. Each frame computes target joint values for the current
 * pose and eases the rig toward them, so pose changes blend smoothly.
 * All angles are offsets from the joint's rest rotation.
 */
import { AnimationMixer, type AnimationAction, type Object3D } from 'three';
import type { RobotFacing, RobotPose } from '../types';
import type { MouthShape } from './face';
import type { Rig } from './rig';

interface Joints {
  armRz: number; armRx: number;
  armLz: number; armLx: number;
  headZ: number; headY: number; headX: number;
  turn: number; hop: number;
  eyeX: number; eyeY: number;
  glow: number;
}

interface Rest {
  rotation: { x: number; y: number; z: number };
  position: { x: number; y: number; z: number };
  scale: { x: number; y: number; z: number };
}

function capture(node?: Object3D): Rest | undefined {
  if (!node) return undefined;
  return {
    rotation: { x: node.rotation.x, y: node.rotation.y, z: node.rotation.z },
    position: { x: node.position.x, y: node.position.y, z: node.position.z },
    scale: { x: node.scale.x, y: node.scale.y, z: node.scale.z },
  };
}

const GREET_SECONDS = 2.6;
const CELEBRATE_SECONDS = 1.6;
// While held, the robot hangs from about head height, so it swings around that point.
const HANG_HEIGHT = 1.9;
// How far the eyes and head follow the pointer at full deflection.
const GAZE = { eyeX: 0.07, eyeY: 0.05, headY: 0.24, headX: 0.12 };

function mouthFor(pose: RobotPose, tp: number): MouthShape {
  switch (pose) {
    case 'flying': return 'grin';
    case 'think': return 'oh';
    case 'success': return 'grin';
    case 'greet': return tp < GREET_SECONDS ? 'grin' : 'smile';
    default: return 'smile';
  }
}

function targetsFor(pose: RobotPose, facing: RobotFacing, t: number, tp: number): Joints {
  const turn = facing === 'left' ? -0.3 : facing === 'right' ? 0.3 : 0;
  const j: Joints = {
    armRz: 0, armRx: 0, armLz: 0, armLx: 0,
    headZ: 0.035 * Math.sin(t * 0.6), headY: turn * 0.6, headX: 0,
    turn, hop: 0,
    eyeX: turn * 0.06, eyeY: 0,
    glow: 0.35,
  };

  switch (pose) {
    case 'greet':
      if (tp < GREET_SECONDS) {
        j.armRz = 2.45 + 0.32 * Math.sin(tp * 8);
        j.armRx = -0.15;
        j.headZ = 0.1;
      }
      break;
    case 'point': {
      const side = facing === 'left' ? -1 : 1;
      const reach = 1.32 + 0.05 * Math.sin(t * 2.6);
      if (side > 0) {
        j.armRz = reach;
        j.armRx = -0.3;
      } else {
        j.armLz = -reach;
        j.armLx = -0.3;
      }
      j.headY = 0.38 * side;
      j.eyeX = 0.04 * side;
      j.headZ = 0.06 * side;
      break;
    }
    case 'think':
      j.armRz = -0.75;
      j.armRx = -2.1;
      j.headZ = -0.16 + 0.03 * Math.sin(t * 1.4);
      j.headX = -0.08;
      j.eyeX = -0.035;
      j.eyeY = 0.035;
      j.glow = 0.4 + 0.9 * (0.5 + 0.5 * Math.sin(t * 5));
      break;
    case 'success':
      if (tp < CELEBRATE_SECONDS) {
        const wiggle = 0.12 * Math.sin(tp * 9);
        j.armRz = 2.2 + wiggle;
        j.armLz = -2.2 - wiggle;
        j.hop = Math.abs(Math.sin(tp * Math.PI * 2.5)) * 0.09 * (1 - tp / CELEBRATE_SECONDS);
      } else {
        j.armRz = 0.45;
        j.armLz = -0.45;
      }
      j.glow = 0.7;
      break;
    case 'flying':
      // Wheee: arms up and waving out of step, head tipped back and swaying, a little
      // bounce, lights pulsing. The happy closed eyes and grin are set below. The pulse
      // stays under two a second, well below flashing rates.
      j.armRz = 2.45 + 0.45 * Math.sin(tp * 15);
      j.armLz = -2.45 - 0.45 * Math.sin(tp * 15 + 1.9);
      j.armRx = 0.25 * Math.sin(tp * 11);
      j.armLx = 0.25 * Math.sin(tp * 13 + 1);
      j.headZ = 0.12 * Math.sin(tp * 9);
      j.headX = -0.12;
      j.hop = 0.025 * Math.abs(Math.sin(tp * 17));
      j.glow = 0.6 + 0.9 * (0.5 + 0.5 * Math.sin(tp * 11));
      break;
    case 'idle':
      break;
  }
  return j;
}

export class RobotAnimator {
  private readonly rig: Rig;
  private readonly rest: Record<string, Rest | undefined>;
  private readonly current: Joints;
  private pose: RobotPose = 'idle';
  private facing: RobotFacing = 'front';
  private poseStartedAt = 0;
  private time = 0;
  private nextBlink = 2.5;
  private readonly mixer?: AnimationMixer;
  private readonly actions = new Map<string, AnimationAction>();
  private activeAction?: AnimationAction;
  private readonly eyeRest: number[];
  private look: { x: number; y: number } | null = null;
  private swingTarget = 0;
  private swing = 0;
  private swingSpeed = 0;

  constructor(rig: Rig) {
    this.rig = rig;
    this.rest = {
      root: capture(rig.root), torso: capture(rig.torso), body: capture(rig.body),
      head: capture(rig.head), armL: capture(rig.armL), armR: capture(rig.armR), eyes: capture(rig.eyes),
    };
    this.current = targetsFor('idle', 'front', 0, 0);
    this.eyeRest = rig.eyeMeshes.map((e) => e.scale.y);
    if (rig.clips.length) {
      this.mixer = new AnimationMixer(rig.root);
      for (const clip of rig.clips) this.actions.set(clip.name.toLowerCase(), this.mixer.clipAction(clip));
    }
  }

  setPose(pose: RobotPose, facing: RobotFacing): void {
    if (pose !== this.pose) this.poseStartedAt = this.time;
    this.pose = pose;
    this.facing = facing;
    const action = this.actions.get(pose) ?? this.actions.get('idle');
    if (action && action !== this.activeAction) {
      action.reset().fadeIn(0.3).play();
      this.activeAction?.fadeOut(0.3);
      this.activeAction = action;
    }
  }

  /**
   * Where the pointer is relative to the robot's head, each axis from -1 to 1 (right and
   * down positive), or null to look where the pose says.
   */
  setLook(look: { x: number; y: number } | null): void {
    this.look = look;
  }

  /** Sideways drag speed in pixels per millisecond: the hanging robot swings against it. */
  nudge(speed: number): void {
    this.swingTarget = Math.max(-0.6, Math.min(0.6, -0.4 * speed));
  }

  /** Advance by dt seconds and write joint values into the rig. */
  update(dt: number): void {
    this.time += dt;
    const t = this.time;
    const target = targetsFor(this.pose, this.facing, t, t - this.poseStartedAt);
    if (this.look && this.pose !== 'flying') {
      target.eyeX += this.look.x * GAZE.eyeX;
      target.eyeY -= this.look.y * GAZE.eyeY;
      target.headY += this.look.x * GAZE.headY;
      target.headX += this.look.y * GAZE.headX;
    }
    const k = 1 - Math.exp(-dt * 9);
    const cur = this.current;
    for (const key of Object.keys(cur) as (keyof Joints)[]) cur[key] += (target[key] - cur[key]) * k;

    this.mixer?.update(dt);
    const usingClip = Boolean(this.activeAction);
    const { rig, rest } = this;

    // Swing like something held from above: a damped spring toward the drag's pull, which
    // fades so the robot swings back and settles once the drag stops.
    this.swingTarget *= Math.exp(-dt * 6);
    this.swingSpeed += ((this.swingTarget - this.swing) * 40 - this.swingSpeed * 7) * dt;
    this.swing += this.swingSpeed * dt;
    const swing = this.swing;

    rig.root.rotation.y = (rest.root?.rotation.y ?? 0) + cur.turn;
    rig.root.rotation.z = (rest.root?.rotation.z ?? 0) + swing;
    rig.root.position.x = (rest.root?.position.x ?? 0) + HANG_HEIGHT * Math.sin(swing);
    rig.root.position.y = (rest.root?.position.y ?? 0) + cur.hop + HANG_HEIGHT * (1 - Math.cos(swing));
    if (rig.shadow) rig.shadow.position.y = 0.005 - cur.hop; // stays on the floor
    if (rig.shadow) rig.shadow.scale.setScalar(1 - cur.hop * 2.5);

    const breath = Math.sin(t * 1.7);
    if (rig.torso && rest.torso) rig.torso.position.y = rest.torso.position.y + 0.012 * breath;
    if (rig.body && rest.body) {
      rig.body.scale.set(rest.body.scale.x * (1 - 0.004 * breath), rest.body.scale.y * (1 + 0.01 * breath), rest.body.scale.z * (1 - 0.004 * breath));
    }

    if (!usingClip) {
      if (rig.armR && rest.armR) {
        rig.armR.rotation.z = rest.armR.rotation.z + cur.armRz;
        rig.armR.rotation.x = rest.armR.rotation.x + cur.armRx;
      }
      if (rig.armL && rest.armL) {
        rig.armL.rotation.z = rest.armL.rotation.z + cur.armLz;
        rig.armL.rotation.x = rest.armL.rotation.x + cur.armLx;
      }
      if (rig.head && rest.head) {
        rig.head.rotation.set(rest.head.rotation.x + cur.headX, rest.head.rotation.y + cur.headY, rest.head.rotation.z + cur.headZ);
      }
    }
    if (rig.eyes && rest.eyes) {
      rig.eyes.position.x = rest.eyes.position.x + cur.eyeX;
      rig.eyes.position.y = rest.eyes.position.y + cur.eyeY;
    }

    // Happy closed eyes while pleased, waving hello or flying; otherwise open eyes that
    // blink every few seconds.
    const tp = t - this.poseStartedAt;
    const waving = this.pose === 'greet' && tp < GREET_SECONDS;
    const happy = (this.pose === 'success' || this.pose === 'flying' || waving) && rig.happyEyes.length > 0;
    if (t > this.nextBlink + 0.16) this.nextBlink = t + 2.4 + Math.random() * 3.2;
    const blinkPhase = (t - this.nextBlink) / 0.16;
    const squash = blinkPhase > 0 && blinkPhase < 1 ? 1 - 0.9 * Math.sin(Math.PI * blinkPhase) : 1;
    rig.eyeMeshes.forEach((eye, i) => {
      eye.visible = !happy;
      eye.scale.y = (this.eyeRest[i] ?? 1) * squash;
    });
    rig.happyEyes.forEach((eye) => (eye.visible = happy));

    if (rig.mouths) {
      const shape = mouthFor(this.pose, tp);
      for (const [name, mouth] of Object.entries(rig.mouths)) mouth.visible = name === shape;
    }

    if (rig.glow) rig.glow.emissiveIntensity = cur.glow;
  }

  dispose(): void {
    this.mixer?.stopAllAction();
  }
}
