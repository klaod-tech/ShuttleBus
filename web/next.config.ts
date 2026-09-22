import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // 저장소 작업 지침은 루트 CLAUDE.md 한 곳에서 관리한다.
  agentRules: false,
  reactStrictMode: true,
  // Docker 이미지에서 node_modules 없이 실행하기 위한 독립 출력 (web/Dockerfile)
  output: "standalone",
};

export default nextConfig;
