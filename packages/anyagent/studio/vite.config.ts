import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  base: "/studio/",
  plugins: [react()],
  build: {
    outDir: "../src/anyagent/studio_static",
    emptyOutDir: true,
  },
  server: {
    port: 5177,
    strictPort: false,
  },
});
