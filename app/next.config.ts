import type { NextConfig } from "next";

// Static export only: no server, no runtime API (ADR 0001). Data is read from
// public/data at build time and also published as-is under /data/.
const config: NextConfig = {
  output: "export",
  trailingSlash: true,
  images: { unoptimized: true },
  poweredByHeader: false,
  experimental: { agentUpgrade: "security" },
};

export default config;
