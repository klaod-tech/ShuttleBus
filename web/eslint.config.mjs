import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

export default defineConfig([
  ...nextVitals,
  ...nextTs,
  {
    files: ["components/KakaoMap.tsx", "types/kakao.d.ts", "tests/**/*.tsx"],
    rules: {
      // Kakao SDK's existing boundary types remain dynamic.
      "@typescript-eslint/no-explicit-any": "off",
    },
  },
  {
    files: ["app/page.tsx", "components/StopCard.tsx"],
    rules: {
      // Effects clear stale server data when the selected route changes.
      "react-hooks/set-state-in-effect": "off",
    },
  },
  globalIgnores([".next/**", "next-env.d.ts"]),
]);
