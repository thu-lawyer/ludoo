/* 公共工具：DOM、toast、防抖、主题 */

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k === "html") node.innerHTML = v;
    else if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2), v);
    else if (v !== null && v !== undefined) node.setAttribute(k, v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined) continue;
    node.append(c.nodeType ? c : document.createTextNode(c));
  }
  return node;
}

export function esc(s) {
  return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

export function toast(msg, type = "info", ms = 2400) {
  let root = $("#toast-root");
  if (!root) {
    root = el("div", { id: "toast-root" });
    document.body.append(root);
  }
  const t = el("div", { class: `toast ${type}` }, msg);
  root.append(t);
  setTimeout(() => { t.style.opacity = "0"; t.style.transition = "opacity .3s"; }, ms - 300);
  setTimeout(() => t.remove(), ms);
}

export function debounce(fn, ms) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}

/* 主题切换（两页共享，存 localStorage；支持 ?theme=dark|light 预览覆盖） */
export function initTheme(toggleSel) {
  const apply = (theme, persist = true) => {
    document.documentElement.dataset.theme = theme;
    if (persist) localStorage.setItem("ludoo-theme", theme);
  };
  const urlTheme = new URLSearchParams(location.search).get("theme");
  const stored = localStorage.getItem("ludoo-theme") || "light";
  apply(urlTheme === "dark" || urlTheme === "light" ? urlTheme : stored, !urlTheme);
  const btn = $(toggleSel);
  if (btn) btn.addEventListener("click", () => {
    const cur = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    apply(cur);
    btn.textContent = cur === "dark" ? "☀" : "☾";
  });
  if (btn) btn.textContent = document.documentElement.dataset.theme === "dark" ? "☀" : "☾";
}

export function fmtDate(iso) {
  if (!iso) return "";
  return iso.slice(0, 10);
}

/* 来源徽标 */
export const SRC_LABEL = { pdf: "PDF", docx: "Word", web: "网页", text: "文本" };
