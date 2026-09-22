import { defineConfig } from "vitest/config";
import { fileURLToPath } from "node:url";

export default defineConfig({
  resolve: { alias: { "@": fileURLToPath(new URL(".", import.meta.url)) } },
  oxc: { jsx: { runtime: "automatic" } },
  test: { environment: "jsdom", include: ["tests/**/*.test.tsx"], env: { NEXT_PUBLIC_KAKAO_MAP_JS_KEY: "demo-test-key" } },
});
