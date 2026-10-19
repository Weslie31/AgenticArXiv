// src/main.ts
import { createApp } from "vue";
import { createPinia } from "pinia";
import App from "./App.vue";

import "./style.css";

// 全局错误捕获：开发期把任何未捕获错误写到页面顶部，方便定位。
// 注意：HMR 会触发 vite 内部的 ErrorEvent（自定义事件），不是真错误，要过滤。
function showFatal(msg: string, stack?: string) {
  // 同一错误只显示一次（按消息内容去重）
  const sig = msg + "|" + (stack || "").slice(0, 200);
  const key = "__fatal_sig__";
  const w = window as any;
  if (w[key] === sig) return;
  w[key] = sig;

  const el = document.createElement("pre");
  el.style.cssText =
    "position:fixed;bottom:0;left:0;right:0;z-index:99999;background:#b00;color:#fff;padding:8px 12px;font:12px/1.4 monospace;white-space:pre-wrap;max-height:40vh;overflow:auto;border-top:2px solid #fff;";
  el.textContent = "[FATAL] " + msg + (stack ? "\n" + stack : "");
  document.body.appendChild(el);
}
function isIgnorable(msg: string): boolean {
  if (!msg) return true;
  // vite 内部 HMR 自定义事件，会被转成 "[object Event]" 这种空信息
  if (msg === "[object Event]" || msg === "Script error.") return true;
  if (msg.includes("ResizeObserver loop")) return true;
  return false;
}
window.addEventListener("error", (e) => {
  const msg = (e as ErrorEvent).message || String((e as any).error || e);
  if (isIgnorable(msg)) return;
  showFatal(msg, ((e as any).error as any)?.stack);
});
window.addEventListener("unhandledrejection", (e) => {
  const reason = (e as any).reason;
  const msg = reason?.message || String(reason);
  if (isIgnorable(msg)) return;
  showFatal("UnhandledRejection: " + msg, reason?.stack);
});

try {
  const app = createApp(App);
  const pinia = createPinia();

  app.use(pinia);

  app.config.errorHandler = (err, instance, info) => {
    const msg = (err as any)?.message || String(err);
    if (isIgnorable(msg)) return;
    showFatal("Vue error: " + msg + " [" + info + "]", (err as any)?.stack);
  };
  app.mount("#app");
} catch (e: any) {
  showFatal("Bootstrap failed: " + (e?.message || e), e?.stack);
}
