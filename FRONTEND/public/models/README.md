# Other robot models (optional)

The DockBrain robot loads from `GLB/dockbrain-companion.glb` at the repository root, so
it isn't stored here.

To use another model, put it here and set `VITE_ROBOT_GLB_URL=/models/<name>.glb` in
`FRONTEND/.env.local`. Set `VITE_ROBOT_GLB_URL=none` for the built-in robot made from
simple shapes. Restart `npm run dev` or rebuild after changing it. Expected part names
and setup are in `../../HANDOFF.md`, section "Replacing the robot with a GLB".
