/// <reference types="vitest" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// O build vai para dentro do pacote Python, que o serve em produção.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "../src/cmlive/web/dist",
    emptyOutDir: true,
    sourcemap: true,
    chunkSizeWarningLimit: 1200, // maplibre-gl tem ~800 kB por si só
  },
  server: {
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: true },
      "/metrics": "http://localhost:8000",
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    css: false,
  },
});
