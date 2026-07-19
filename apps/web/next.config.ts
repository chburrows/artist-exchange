import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Static export: a true SPA, no SSR data path. See CLAUDE.md.
  output: "export",
};

export default nextConfig;
