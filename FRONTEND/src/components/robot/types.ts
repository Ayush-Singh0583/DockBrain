/**
 * What the robot is doing. Each renderer (3D and SVG) implements every pose. 'flying' is
 * shown while someone carries the robot with the pointer: happy closed eyes and a grin.
 */
export type RobotPose = 'idle' | 'greet' | 'point' | 'think' | 'success' | 'flying';

/** Where the robot looks, and which way it points in the 'point' pose (viewer's side). */
export type RobotFacing = 'front' | 'left' | 'right';

/** 'full' shows the whole robot; 'bust' frames head and shoulders for compact layouts. */
export type RobotCrop = 'full' | 'bust';

export interface RobotRenderProps {
  pose: RobotPose;
  facing: RobotFacing;
  crop: RobotCrop;
}
