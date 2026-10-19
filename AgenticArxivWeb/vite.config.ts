import { fileURLToPath, URL } from "node:url"
import { defineConfig } from "vite"
import vue from "@vitejs/plugin-vue"

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
        secure: false,
      },
    },
  },
  // 关键：预构建 pdfjs-dist，并把 worker 当成「绝对不能被 vite 重新打包的资源」处理。
  // 否则 vue-pdf-embed 在浏览器里要 import 内置的 1.5MB base64 worker data URL，
  // 启动模块 worker 会卡 10s+；改成 vite 直接 serve 真实 mjs 后约 0.8s。
  optimizeDeps: {
    include: ["pdfjs-dist"],
  },
  worker: {
    format: "es",
  },
})
