/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_DOCKBRAIN_API_URL?: string;
  readonly VITE_ROBOT_GLB_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
