/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_BACKEND_PORT?: string
  readonly VITE_FRONTEND_PORT?: string
  readonly VITE_PG_PORT?: string
  readonly VITE_REDIS_PORT?: string
  readonly VITE_CHROMA_PORT?: string
  readonly VITE_FUNASR_PORT?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
