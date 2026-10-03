/// <reference types="vite/client" />
interface ImportMeta {
  readonly env: ImportMetaEnv;
}
interface ImportMetaEnv extends Readonly<Record<string, string>> {
  readonly DEV: boolean;
  readonly PROD: boolean;
  readonly MODE: string;
  readonly SSR: boolean;
}
