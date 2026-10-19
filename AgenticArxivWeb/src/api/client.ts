// src/api/client.ts
import axios from "axios";

// 默认用相对路径：浏览器按当前页面地址请求，Vite 开发服务器/反向代理会把 /api
// 转发到后端。这样从别的机器访问 http://<服务器IP>:5173 也能正常工作。
const baseURL = import.meta.env.VITE_API_BASE || "/api";

export const api = axios.create({
  baseURL,
  timeout: 240000,
  headers: { "Content-Type": "application/json" },
  withCredentials: true,
});

export function getApiBase() {
  return baseURL;
}

