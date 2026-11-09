import { useEffect, useRef, type RefObject } from 'react';
import { ROBOT_GLB_URL } from '../capabilities';
import type { RobotRenderProps } from '../types';
import { createRobotStage, type RobotStage } from './stage';

interface Props extends RobotRenderProps {
  onReady: () => void;
  onFail: () => void;
  /** Called with 0 once the 3D engine has loaded, then with the model's downloaded fraction (0–1). */
  onProgress?: (fraction: number) => void;
  /** Receives the live stage, for hit testing and drag sway; null when there is none. */
  stageRef?: RefObject<RobotStage | null>;
}

/** React wrapper around the three.js stage. Loaded lazily by RobotMascot. */
export default function Robot3D({ pose, facing, crop, onReady, onFail, onProgress, stageRef }: Props) {
  const hostRef = useRef<HTMLDivElement>(null);
  const ownStageRef = useRef<RobotStage | null>(null);
  const latest = useRef({ pose, facing, crop });
  latest.current = { pose, facing, crop };

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    let stage: RobotStage;
    try {
      onProgress?.(0); // this code arriving means the 3D engine has loaded
      stage = createRobotStage(host, { crop: latest.current.crop, glbUrl: ROBOT_GLB_URL || undefined, onReady, onFail, onProgress });
    } catch {
      onFail();
      return;
    }
    stage.setPose(latest.current.pose, latest.current.facing);
    ownStageRef.current = stage;
    if (stageRef) stageRef.current = stage;
    return () => {
      ownStageRef.current = null;
      if (stageRef?.current === stage) stageRef.current = null;
      stage.dispose();
    };
  }, [onReady, onFail, onProgress, stageRef]);

  useEffect(() => {
    ownStageRef.current?.setPose(pose, facing);
  }, [pose, facing]);

  // Changing the crop (a robot lifted out of a head-and-shoulders slot) keeps the same stage.
  useEffect(() => {
    ownStageRef.current?.setCrop(crop);
  }, [crop]);

  return <div ref={hostRef} style={{ position: 'absolute', inset: 0 }} />;
}
