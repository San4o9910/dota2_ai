import type { NextConfig } from "next";
import { createSecurityHeaderRules } from "./config/security-headers.mjs";

const nextConfig: NextConfig = {
  // Vinext resolves the standard Next.js headers() contract for Worker
  // responses, so this remains portable between Next and the Sites runtime.
  headers: async () => createSecurityHeaderRules(),
};

export default nextConfig;
