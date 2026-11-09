# DockBrain frontend

A web interface for DockBrain, guided by a friendly robot: pick an activity, provide a
document or project folder, then read notes, ask questions, take a quiz, flip memory cards
or explore a codebase overview.

Every screen has the same shape: the robot hosts it on a coloured stage across the top, and
a white card rises over the stage's edge to hold the work. There is a light theme (a vivid
blue stage) and a dark theme. The page follows the system setting, and the sun/moon button
in the top bar overrides it; the choice is kept in this browser.

**Without a backend it runs in demo mode.** Results come from built-in samples, and every
screen says so. Choosing files and folders, and checking their type, size and contents
list, is real and happens on your device. Nothing is uploaded or read in demo mode. To use
real documents, start the backend and set `VITE_DOCKBRAIN_API_URL`, as the
[README at the repository root](../README.md) explains. See `HANDOFF.md` for exactly what
is real and what is sample content.

## Requirements

- Node.js 22.22+ or 24.15+ (the test tools require it; developed with Node 24.20 and npm 11.19)
- For `npm run screenshots` only: an installed Google Chrome or Chromium

## Install and run

All commands run from this `FRONTEND/` folder.

```bash
cd FRONTEND
npm install          # installs from package-lock.json
npm run dev          # development server at http://localhost:5173
```

Production build and local preview:

```bash
npm run build        # type-checks, then builds into dist/
npm run preview      # serves dist/ at http://localhost:4173
```

Checks:

```bash
npm run typecheck    # TypeScript only
npm test             # unit and interaction tests (Vitest + Testing Library, jsdom)
npm run screenshots  # with `npm run preview` running: walks every screen in Chrome at
                     # desktop, tablet and phone sizes, saves screenshots/ and reports
                     # sideways scrolling, page errors and console errors
                     # (THEME=dark walks the dark theme, into screenshots/dark/)
```

`python3 scripts/mutation-check.py` makes 140 small deliberate bugs, one at a time, and
confirms the test suite catches each.

`npm run screenshots desktop` (or `tablet`, `phone`) limits it to one size. Set
`CHROME_PATH` if Chrome isn't in a standard location, and `BASE_URL` to test another
server.

## Configuration

Copy `.env.example` to `.env.local`. Every `VITE_*` value is visible in the browser, so
never put Gemini, Claude or other provider keys here. Keys belong on the server.

| Variable | Effect |
| --- | --- |
| `VITE_DOCKBRAIN_API_URL` | Base URL of a server implementing `API_CONTRACT.md`. Empty means demo mode. |
| `VITE_ROBOT_GLB_URL` | Robot model. Empty means the DockBrain robot, `GLB/dockbrain-companion.glb` at the repository root. A URL such as `/models/other.glb` loads another GLB/GLTF model, and `none` uses the built-in robot made from simple shapes. |

## Useful URL switches

| URL | Effect |
| --- | --- |
| `?robot=2d` | Use the lightweight SVG robot instead of the 3D one. |
| `?simulate=ask-error` | Demo mode only: the first answer request fails, to show the error and retry states. Also `open-error`, `notes-error`, `quiz-error`, `codebase-error`; combine with commas. |

The SVG robot is also used automatically when WebGL is unavailable or the system asks
for reduced motion.

## The robot

The 3D robot is `GLB/dockbrain-companion.glb`, built from simple shapes by
`npm run robot-model` (`scripts/build-robot-model.mjs`); edit that script and rerun it to
change the robot's look. The flat SVG robot in `src/components/robot/RobotFallback.tsx`
is drawn to match.

Its eyes follow the pointer. Drag it to pick it up (on touch screens, long-press first,
so swiping over it still scrolls). While it's moving it flies happily, eyes closed and
grinning, and it settles when held
still, and it stays where you leave it until you move to another screen. A click on it
just makes it giggle. It says a short line in a bubble while carried, when it lands and
when clicked. Only the robot itself can be grabbed: clicks on the empty space around it
reach the page. With reduced motion it is a still drawing, which can still be moved.

## Project layout

```text
src/
  app/          App shell, navigation state (state.ts), top bar and theme switch, focus handling
  screens/      Welcome, Select (file/folder pickers), Workspace (Notes/Ask/Quiz), Codebase
  components/   RobotMascot (+ robot3d/ for three.js), evidence (citations, sources), shared UI
  services/     DockBrainService interface, mock (demo) and HTTP (draft) adapters, types
  fixtures/     Demo content, kept apart from components
  lib/          File validation, folder reading, citation parsing, formatting, theme (theme.ts)
  styles/       Design tokens (every colour is a light/dark pair) and base styles
scripts/        screenshots.mjs (browser walkthrough)
screenshots/    Saved screenshots of every screen (screenshots/dark/ for the dark theme)
```

Related documents: `API_CONTRACT.md` (proposed backend API), `HANDOFF.md` (status,
checks, known gaps, robot replacement).
