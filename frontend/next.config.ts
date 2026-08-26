import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Don't regenerate AGENTS.md/CLAUDE.md on every `next dev` -- this repo
  // has its own root CLAUDE.md as the single source of truth for agent
  // guidance (see CLAUDE.md), a nested one here would just be confusing.
  agentRules: false,
  // Standalone output for a lean Docker image (see Dockerfile) -- copies
  // only the traced production dependencies, not the full node_modules.
  output: "standalone",
};

export default nextConfig;
