import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Docker 이미지에서 node_modules 없이 실행하기 위한 독립 출력 (web/Dockerfile)
  output: "standalone",
};

export default nextConfig;
