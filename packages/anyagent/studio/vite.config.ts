import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Studio 前端独立部署（方案 B）：
// - base 通过 VITE_BASE 配置，默认 "/"（独立站点根路径）。
//   挂载到 server /studio/ 子路径时设 VITE_BASE=/studio/。
// - outDir 默认本地 dist/，不再写入 Python 包内。
//   本地开发若想让 `anyagent serve` 挂载，可 build 后设
//   ANYAGENT_STUDIO_DIR 指向此 dist 目录。
const base = process.env.VITE_BASE ?? "/";

export default defineConfig({
  base,
  plugins: [react()],
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
  server: {
    port: 5177,
    strictPort: false,
  },
});
