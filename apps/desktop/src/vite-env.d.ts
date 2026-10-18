/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** 浏览器单独开发时 Core Service 的地址，如 http://127.0.0.1:8765 */
  readonly VITE_CORE_URL?: string;
  /** 浏览器单独开发时的会话 token（freeread-core --token 给的值） */
  readonly VITE_CORE_TOKEN?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
