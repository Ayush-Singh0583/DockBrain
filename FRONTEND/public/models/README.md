# Other robot models (optional)

The DockBrain robot loads from `GLB/dockbrain-companion.glb` at the repository root, so
it isn't stored here.

To use another model, put it here and set `VITE_ROBOT_GLB_URL=/models/<name>.glb` in
`FRONTEND/.env.local`. Set `VITE_ROBOT_GLB_URL=none` for the built-in robot made from
simple shapes. Restart `npm run dev` or rebuild after changing it.

## Setting up a model

- **Size and position:** any size or origin works. It's scaled to 2.4 units tall, with its
  feet on the floor, and centred. Face +Z (toward the camera), with Y up, as glTF expects.
- **Part names:** name nodes so the built-in poses can move them. Matching ignores case,
  spaces, `_`, `-` and `.`.

  | Node | What it does |
  | --- | --- |
  | `Head` | Tilts and turns. Pivot at the neck. |
  | `ArmL`, `ArmR` | The viewer's left and right. Pivot at the shoulder, hanging down at rest. |
  | `Torso` or `Body` | Moves gently while breathing. |
  | `Eyes` | A group moved to change where it looks. |
  | `EyeL`, `EyeR` | Squashed to blink. |
  | `HappyEyeL`, `HappyEyeR` | Shown when celebrating. |
  | `Glow`, `ChestGlow` or `AntennaLight` | A light that pulses while thinking. |

  A missing node only skips that motion.
- **Animations:** clips named `idle`, `greet`, `point`, `think` or `success` play for that
  pose instead of the built-in arm and head motion.

If a model fails to load, the app uses its built-in robot and logs one console warning.
