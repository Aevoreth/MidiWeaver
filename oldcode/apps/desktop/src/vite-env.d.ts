declare module "*.css";

interface ImportMetaEnv {
  readonly VITE_ENGINE_URL: string;
  readonly VITE_AI_MOCK?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
