import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

// CC_WEB_PORT / CC_API let a second copy of the UI point at a different backend (e.g. a scratch database).
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "CC_");
  return {
    plugins: [react()],
    server: {
      port: Number(env.CC_WEB_PORT ?? 5174),
      proxy: { "/api": { target: env.CC_API ?? "http://localhost:8100", changeOrigin: true, timeout: 900000, proxyTimeout: 900000 } },
    },
  };
});
