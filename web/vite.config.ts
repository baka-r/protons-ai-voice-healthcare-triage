import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://agent:8000", changeOrigin: true },
      "/ws": { target: "ws://agent:8000", ws: true, changeOrigin: true },
    },
  },
  build: { chunkSizeWarningLimit: 2500 },
});
