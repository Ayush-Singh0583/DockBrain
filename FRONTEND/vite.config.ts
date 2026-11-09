/// <reference types="vitest/config" />
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  // Robot models are binary assets: the app imports the robot from the repository's GLB/.
  assetsInclude: ['**/*.glb'],
  // Besides this folder, the dev server may serve only GLB/, not the rest of the repository
  // (whose root holds the backend's .env with provider keys).
  server: { port: 5173, strictPort: false, fs: { allow: ['.', '../GLB'] } },
  build: {
    // three.js lives in its own lazily loaded chunk (see src/components/robot/robot3d).
    chunkSizeWarningLimit: 800,
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    restoreMocks: true,
  },
});
