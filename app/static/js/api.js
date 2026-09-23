/* 后端 API 封装 */
import { toast } from "./common.js";

async function request(path, options = {}) {
  const resp = await fetch(path, {
    headers: options.body && !(options.body instanceof FormData)
      ? { "Content-Type": "application/json" } : undefined,
    ...options,
  });
  if (resp.status === 401 && !path.startsWith("/api/ai/status")) {
    // 会话过期（公网口令模式）：回登录页
    location.href = "/login";
    throw new Error("未登录");
  }
  if (!resp.ok) {
    let msg = `请求失败（${resp.status}）`;
    try {
      const data = await resp.json();
      if (data.detail) msg = String(data.detail);
    } catch { /* 忽略非 JSON 错误体 */ }
    throw new Error(msg);
  }
  return resp.json();
}

export const api = {
  listDocs: (params = {}) => {
    const qs = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== "" && v !== null && v !== undefined));
    return request(`/api/documents?${qs}`);
  },
  getDoc: (id) => request(`/api/documents/${id}`),
  patchDoc: (id, fields) => request(`/api/documents/${id}`, {
    method: "PATCH", body: JSON.stringify(fields),
  }),
  delDoc: (id) => request(`/api/documents/${id}`, { method: "DELETE" }),

  upload: (file) => {
    const fd = new FormData();
    fd.append("file", file);
    return request("/api/documents/upload", { method: "POST", body: fd });
  },
  importUrl: (url) => request("/api/documents/url", {
    method: "POST", body: JSON.stringify({ url }),
  }),
  importText: (title, text) => request("/api/documents/text", {
    method: "POST", body: JSON.stringify({ title, text }),
  }),

  tags: () => request("/api/tags"),
  stats: () => request("/api/stats"),
  search: (q) => request(`/api/search?q=${encodeURIComponent(q)}`),

  annotations: (docId) => request(`/api/documents/${docId}/annotations`),
  addAnnotation: (docId, ann) => request(`/api/documents/${docId}/annotations`, {
    method: "POST", body: JSON.stringify(ann),
  }),
  patchAnnotation: (id, fields) => request(`/api/annotations/${id}`, {
    method: "PATCH", body: JSON.stringify(fields),
  }),
  delAnnotation: (id) => request(`/api/annotations/${id}`, { method: "DELETE" }),

  aiStatus: () => request("/api/ai/status"),
  aiSummarize: (docId) => request(`/api/documents/${docId}/summarize`, { method: "POST" }),
  aiExplain: (text, context = "") => request("/api/ai/explain", {
    method: "POST", body: JSON.stringify({ text, context }),
  }),
};

export function apiErr(e) {
  toast(e.message || "操作失败", "error");
}
