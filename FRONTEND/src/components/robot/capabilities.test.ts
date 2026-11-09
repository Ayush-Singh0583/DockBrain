import { resolveRobotGlbUrl, ROBOT_GLB_URL } from './capabilities';

describe('which robot model loads', () => {
  it('loads the DockBrain robot from the GLB folder when nothing is configured', () => {
    expect(ROBOT_GLB_URL).toMatch(/\/GLB\/dockbrain-companion\.glb$/);
    expect(resolveRobotGlbUrl(undefined, '/robot.glb')).toBe('/robot.glb');
    expect(resolveRobotGlbUrl('  ', '/robot.glb')).toBe('/robot.glb');
  });

  it('uses a configured model instead', () => {
    expect(resolveRobotGlbUrl(' /models/other.glb ', '/robot.glb')).toBe('/models/other.glb');
  });

  it('uses the built-in robot when set to none', () => {
    expect(resolveRobotGlbUrl('none', '/robot.glb')).toBe('');
    expect(resolveRobotGlbUrl('None', '/robot.glb')).toBe('');
  });
});
