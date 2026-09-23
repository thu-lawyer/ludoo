/* 阅读器页：渲染、进度、目录、批注、法条、信息、AI */
import { $, $$, el, esc, toast, debounce, initTheme, fmtDate, SRC_LABEL } from "./common.js";
import { api, apiErr } from "./api.js";
import { gbt7714 } from "./citation.js";
import { ANN_TYPES, getSelectionInfo, applyAnnotations, wrapAnnotation, overlaps, showToolbar, hideToolbar } from "./annotate.js";

const params = new URLSearchParams(location.search);
const docId = Number(params.get("id"));
if (!docId) { location.href = "/"; throw new Error("missing id"); }

let doc = null;
let annotations = [];
let aiOn = false;

initTheme("#theme-toggle");
$("#back-btn").addEventListener("click", () => { location.href = "/"; });
$("#panel-toggle").addEventListener("click", () => $("#reader-body").classList.toggle("panel-hidden"));

/* 字号 */
let readerSize = Number(localStorage.getItem("ludoo-size")) || 18;
function applySize() {
  document.documentElement.style.setProperty("--reader-size", `${readerSize}px`);
  localStorage.setItem("ludoo-size", readerSize);
}
applySize();
$("#font-dec").addEventListener("click", () => { readerSize = Math.max(15, readerSize - 1); applySize(); });
$("#font-inc").addEventListener("click", () => { readerSize = Math.min(24, readerSize + 1); applySize(); });

/* ---------- 加载与渲染 ---------- */

async function load() {
  try {
    [doc, annotations] = await Promise.all([api.getDoc(docId), api.annotations(docId)]);
  } catch (e) { apiErr(e); location.href = "/"; return; }
  aiStatus().then();
  document.title = `${doc.title} · 律读`;
  $("#top-title").textContent = doc.title;
  renderArticle();
  applyAnnotations($("#article"), annotations);
  restoreProgress();
  bindSelection();
  switchPane("toc");
  if (params.get("goto")) {
    const target = document.getElementById(params.get("goto"));
    if (target) setTimeout(() => target.scrollIntoView({ block: "center" }), 120);
  }
}

function renderArticle() {
  const art = $("#article");
  const blocks = [...doc.blocks];
  // 若首块是大标题且与文献标题同文，则并入头部不再重复渲染
  let skipFirst = false;
  if (blocks.length && blocks[0].type === "h1") {
    const norm = (s) => s.replace(/\s+/g, "");
    if (norm(blocks[0].text).startsWith(norm(doc.title).slice(0, 12))
      || norm(doc.title).startsWith(norm(blocks[0].text).slice(0, 12))) skipFirst = true;
  }

  const kicker = el("div", { class: "kicker" },
    el("span", { class: `src-badge ${doc.source_type}` }, SRC_LABEL[doc.source_type] || doc.source_type),
    doc.source_url ? el("a", { href: doc.source_url, target: "_blank", rel: "noopener" }, "查看原文 ↗") : null);
  const byline = [doc.author, doc.year, doc.publication].filter(Boolean);
  const head = el("header", { class: "doc-head" },
    kicker, el("h1", {}, esc(doc.title)),
    byline.length ? el("div", { class: "byline" }, byline.map((s) => el("span", {}, esc(s)))) : null);

  const frag = document.createDocumentFragment();
  frag.append(head);
  blocks.forEach((b, i) => {
    if (i === 0 && skipFirst) return;
    const node = document.createElement(b.type === "quote" ? "blockquote" : (b.type.startsWith("h") ? b.type : "p"));
    node.className = "blk";
    node.id = b.id;
    node.innerHTML = b.html || esc(b.text);
    frag.append(node);
  });
  frag.append(el("div", { class: "end-mark" }, "— 完 —"));
  art.replaceChildren(frag);
}

/* ---------- 阅读进度 ---------- */

const scroller = $("#content-scroll");
let lastSent = -1;
let progressReady = false; // 初始定位完成前不回写进度，避免加载期滚动事件覆盖历史进度
scroller.addEventListener("scroll", () => {
  const max = scroller.scrollHeight - scroller.clientHeight;
  if (!progressReady || max <= 0) return;
  const p = Math.min(1, scroller.scrollTop / max);
  $("#pct").textContent = `${Math.round(p * 100)}%`;
  sendProgress(p);
});
const sendProgress = debounce((p) => {
  if (Math.abs(p - lastSent) < 0.01) return;
  lastSent = p;
  api.patchDoc(docId, { progress: p }).catch(() => {});
}, 600);

function restoreProgress() {
  const max = scroller.scrollHeight - scroller.clientHeight;
  if (doc.progress > 0 && doc.progress < 1 && max > 0) {
    scroller.scrollTop = doc.progress * max;
  }
  $("#pct").textContent = `${Math.round((doc.progress || 0) * 100)}%`;
  lastSent = doc.progress || 0;
  requestAnimationFrame(() => { progressReady = true; });
}

/* ---------- 划选批注 ---------- */

function hlColor(type) {
  return getComputedStyle(document.documentElement).getPropertyValue(`--hl-${type}`).trim() || "#f6d878";
}

function bindSelection() {
  const art = $("#article");
  document.addEventListener("mouseup", (ev) => {
    if (ev.button !== 0) return;
    if (toolbarClicked(ev)) return;
    setTimeout(() => {
      const info = getSelectionInfo();
      if (!info) { hideToolbar(); return; }
      if (overlaps(annotations, info.blockId, info.start, info.end)) {
        toast("所选文字与已有批注重叠");
        hideToolbar();
        return;
      }
      const actions = ANN_TYPES.map((t) => ({
        label: t, color: hlColor(t), onPick: () => createAnnotation(t, info),
      }));
      actions.push({ sep: true });
      actions.push({ label: "复制", onPick: async () => {
        try { await navigator.clipboard.writeText(info.text); toast("已复制"); } catch { toast("复制失败", "error"); }
      } });
      if (aiOn) actions.push({ label: "✦ 解释", onPick: () => explainSelection(info.text) });
      const sel = window.getSelection();
      const rect = sel.getRangeAt(0).getBoundingClientRect();
      showToolbar(rect, actions);
    }, 0);
  });
  scroller.addEventListener("scroll", hideToolbar);
  document.addEventListener("keydown", (ev) => { if (ev.key === "Escape") hideToolbar(); });
  // 点击已有高亮 → 侧栏定位
  art.addEventListener("click", (ev) => {
    const mark = ev.target.closest("mark.hl");
    if (!mark) return;
    switchPane("ann");
    const card = $(`#panel-body .ann-card[data-ann-id="${mark.dataset.annId}"]`);
    if (card) {
      card.scrollIntoView({ block: "center", behavior: "smooth" });
      card.classList.add("flash");
      setTimeout(() => card.classList.remove("flash"), 1700);
    }
  });
}

function toolbarClicked(ev) {
  return ev.target.closest && ev.target.closest(".sel-toolbar");
}

async function createAnnotation(type, info) {
  try {
    const r = await api.addAnnotation(docId, {
      type, quote: info.text,
      block_id: info.blockId, start: info.start, end: info.end,
    });
    const ann = { id: r.id, document_id: docId, type, quote: info.text,
      block_id: info.blockId, start: info.start, end: info.end, comment: "", created_at: "" };
    annotations.unshift(ann);
    const block = document.getElementById(info.blockId);
    if (block) wrapAnnotation(block, ann);
    toast(`已标记「${type}」`);
    switchPane("ann");
    flashAnnCard(ann.id);
  } catch (e) { apiErr(e); }
}

function flashAnnCard(annId) {
  const card = $(`#panel-body .ann-card[data-ann-id="${annId}"]`);
  if (card) {
    card.scrollIntoView({ block: "center" });
    card.classList.add("flash");
    setTimeout(() => card.classList.remove("flash"), 1700);
  }
}

/* ---------- 侧栏面板 ---------- */

const PANEL_TABS = { toc: renderToc, ann: renderAnnPane, law: renderLawPane, info: renderInfoPane };
let currentPane = "toc";
let annFilter = "";

$$(".panel-tabs .tab").forEach((t) => t.addEventListener("click", () => switchPane(t.dataset.pane)));

function switchPane(pane) {
  currentPane = pane;
  $$(".panel-tabs .tab").forEach((t) => t.classList.toggle("active", t.dataset.pane === pane));
  PANEL_TABS[pane]();
}

function scrollToBlock(blockId, flash = true) {
  const node = document.getElementById(blockId);
  if (!node) return;
  node.scrollIntoView({ block: "start", behavior: "smooth" });
  if (flash) {
    node.style.transition = "background .4s";
    node.style.background = "var(--gold-soft)";
    setTimeout(() => { node.style.background = ""; }, 1400);
  }
}

function renderToc() {
  const items = doc.blocks.filter((b) => b.type.startsWith("h"));
  const body = $("#panel-body");
  if (!items.length) {
    body.replaceChildren(el("div", { class: "muted small", style: "padding:8px 2px" }, "本文未识别出标题结构。"));
    return;
  }
  body.replaceChildren(...items.map((b) => el("button", {
    class: `toc-item lv-${b.type}`,
    onclick: () => scrollToBlock(b.id),
  }, esc(b.text))));
}

function renderAnnPane() {
  const body = $("#panel-body");
  const chips = el("div", { class: "ann-filter" },
    el("span", { class: `chip${!annFilter ? " active" : ""}`, onclick: () => { annFilter = ""; renderAnnPane(); } }, `全部 ${annotations.length}`),
    ...ANN_TYPES.map((t) => {
      const n = annotations.filter((a) => a.type === t).length;
      return el("span", {
        class: `chip${annFilter === t ? " active" : ""}`,
        style: n ? "" : "opacity:.4",
        onclick: () => { annFilter = annFilter === t ? "" : t; renderAnnPane(); },
      }, `${t} ${n}`);
    }));
  const exportBtn = el("button", { class: "btn small", style: "margin-bottom:12px", onclick: exportNotes }, "⇩ 导出笔记 Markdown");

  const list = annotations.filter((a) => !annFilter || a.type === annFilter);
  body.replaceChildren(chips, el("div", {}, exportBtn));
  if (!list.length) {
    body.append(el("div", { class: "muted small", style: "line-height:1.8" },
      "在正文中划选文字即可添加高亮与批注。\n四种类型：重点（金）、质疑（红）、疑问（青）、联想（紫）。"));
    return;
  }
  body.append(...list.map(annCard));
}

function annCard(a) {
  const commentDiv = el("div", { class: "comment" }, a.comment ? esc(a.comment) : el("span", { class: "muted small" }, "（点击 ✎ 添加心得…）"));
  const card = el("div", { class: "ann-card", "data-type": a.type, "data-ann-id": a.id },
    el("div", { class: "row" },
      el("span", { class: "type-tag" }, `${a.type} · ${fmtDate(a.created_at)}`),
      el("span", { class: "spacer" })),
    el("div", { class: "quote", title: "点击定位到原文", onclick: () => scrollToBlock(a.block_id) }, `「${a.quote}」`),
    commentDiv,
    el("div", { class: "actions" },
      el("button", { onclick: () => editComment(a, commentDiv) }, "✎ 批注"),
      el("button", { onclick: () => locateAnn(a) }, "➤ 定位"),
      el("span", { class: "spacer" }),
      el("button", { class: "del", onclick: async () => {
        if (!confirm("删除这条批注？")) return;
        try {
          await api.delAnnotation(a.id);
          annotations = annotations.filter((x) => x.id !== a.id);
          const mark = $(`#article mark[data-ann-id="${a.id}"]`);
          if (mark) mark.replaceWith(...mark.childNodes);
          renderAnnPane();
        } catch (e) { apiErr(e); }
      } }, "🗑 删除"),
    ));
  return card;
}

function locateAnn(a) {
  const mark = $(`#article mark[data-ann-id="${a.id}"]`);
  if (mark) {
    mark.scrollIntoView({ block: "center", behavior: "smooth" });
    mark.classList.add("flash");
    setTimeout(() => mark.classList.remove("flash"), 1700);
  } else scrollToBlock(a.block_id);
}

function editComment(a, commentDiv) {
  const ta = el("textarea", { placeholder: "写下你的思考、质疑或联想…" });
  ta.value = a.comment || "";
  const save = el("button", { class: "btn primary small", onclick: async () => {
    try {
      await api.patchAnnotation(a.id, { comment: ta.value });
      a.comment = ta.value;
      renderAnnPane();
      flashAnnCard(a.id);
    } catch (e) { apiErr(e); }
  } }, "保存");
  commentDiv.replaceChildren(ta, el("div", { class: "row", style: "margin-top:6px" },
    save, el("span", { class: "muted small" }, "Esc 取消")));
  ta.focus();
  ta.addEventListener("keydown", (ev) => { if (ev.key === "Escape") renderAnnPane(); });
}

function renderLawPane() {
  const body = $("#panel-body");
  if (!doc.statutes.length) {
    body.replaceChildren(el("div", { class: "muted small", style: "padding:8px 2px;line-height:1.8" },
      "本文未识别到《法律》第x条式的法条引用。\n支持如：《民法典》第1043条、《刑法》第一百三十三条之一。"));
    return;
  }
  body.replaceChildren(
    el("div", { class: "muted small", style: "margin-bottom:10px" }, `共识别 ${doc.statutes.length} 部/条法条引用，点击定位原文：`),
    ...doc.statutes.map((s) => el("button", {
      class: "statute-item",
      onclick: () => {
        const names = [s.law, s.law_short].filter(Boolean);
        let span = null;
        for (const n of names) {
          span = $(`#article .statute[data-law="${CSS.escape(n)}"][data-article="${CSS.escape(s.article_label)}"]`);
          if (span) break;
        }
        if (span) {
          span.scrollIntoView({ block: "center", behavior: "smooth" });
          span.style.background = "var(--gold-soft)";
          setTimeout(() => { span.style.background = ""; }, 1500);
        }
      },
    },
      el("span", { class: "law" }, `《${esc(s.law_short || s.law)}》`),
      el("span", { class: "art" }, esc(s.article_label)),
      el("span", { class: "n" }, `${s.count} 次`))),
  );
}

async function renderInfoPane() {
  const body = $("#panel-body");
  body.replaceChildren(el("div", { class: "muted small" }, "加载中…"));
  let fresh = doc;
  try { fresh = await api.getDoc(docId); doc = fresh; } catch { /* 用缓存 */ }

  const citType = el("select", {},
    el("option", { value: "journal" }, "期刊论文 [J]"),
    el("option", { value: "web" }, "网页/电子 [EB/OL]"),
    el("option", { value: "book" }, "专著 [M]"));
  citType.value = doc.source_type === "web" ? "web" : (doc.publication ? "journal" : "web");
  const citBox = el("div", { class: "citation-box" });
  const fields = {};
  const mkInput = (key, label, val) => {
    fields[key] = val;
    const inp = el("input", { value: val, style: "width:100%" });
    inp.oninput = () => { fields[key] = inp.value; update(); };
    return el("div", { class: "field" }, el("label", {}, label), inp);
  };
  const update = () => {
    citBox.textContent = gbt7714({ ...fields, title: doc.title, url: doc.source_url }, citType.value);
  };
  citType.onchange = update;

  body.replaceChildren(el("div", { class: "info-rows" },
    el("div", { class: "info-kv" }, el("span", { class: "k" }, "来源"), el("span", { class: "v" }, SRC_LABEL[doc.source_type] || doc.source_type)),
    doc.source_url ? el("div", { class: "info-kv" }, el("span", { class: "k" }, "原文链接"),
      el("span", { class: "v" }, el("a", { href: doc.source_url, target: "_blank", rel: "noopener" }, doc.source_url.slice(0, 46) + "…"))) : null,
    el("div", { class: "info-kv" }, el("span", { class: "k" }, "字数"), el("span", { class: "v" }, `${doc.word_count} 字`)),
    el("div", { class: "info-kv" }, el("span", { class: "k" }, "批注"), el("span", { class: "v" }, `${annotations.length} 条`)),
    el("div", { class: "info-kv" }, el("span", { class: "k" }, "导入时间"), el("span", { class: "v" }, fmtDate(doc.created_at))),
    mkInput("author", "作者", doc.author || ""),
    el("div", { style: "display:grid;grid-template-columns:1fr 1fr;gap:10px" },
      mkInput("year", "年份", doc.year || ""), mkInput("publication", "期刊/出处", doc.publication || "")),
    el("div", { class: "field" }, el("label", {}, "参考文献（GB/T 7714—2015）"),
      el("div", { class: "row" }, citType,
        el("button", { class: "btn small", onclick: async () => {
          try { await navigator.clipboard.writeText(citBox.textContent); toast("✓ 引用已复制"); }
          catch { toast("复制失败", "error"); }
        } }, "⧉ 复制"))),
    citBox,
    el("button", { class: "btn primary", onclick: async () => {
      try {
        await api.patchDoc(docId, { author: fields.author, year: fields.year, publication: fields.publication });
        toast("✓ 已保存");
      } catch (e) { apiErr(e); }
    } }, "保存信息"),
  ));
  update();
}

/* ---------- 笔记导出 ---------- */

function exportNotes() {
  const order = new Map(doc.blocks.map((b, i) => [b.id, i]));
  const sorted = [...annotations].sort((a, b) =>
    (order.get(a.block_id) ?? 0) - (order.get(b.block_id) ?? 0) || a.start - b.start);
  const cit = gbt7714({
    author: doc.author, title: doc.title, year: doc.year,
    publication: doc.publication, url: doc.source_url,
  }, doc.source_type === "web" ? "web" : doc.publication ? "journal" : "web");

  const lines = [
    `# ${doc.title} · 阅读笔记`, "",
    `> ${cit}`, "",
    `- 批注 ${annotations.length} 条 · ${doc.word_count} 字 · ${fmtDate(doc.created_at)} 导入`, "",
  ];
  for (const a of sorted) {
    lines.push(`## 【${a.type}】`, "", `> ${a.quote}`, "");
    if (a.comment) lines.push(a.comment, "");
  }
  if (!sorted.length) lines.push("_（暂无批注）_", "");
  lines.push("---", "", `_导出自 律读 LuDoo · ${new Date().toLocaleString("zh-CN")}_`);

  const blob = new Blob([lines.join("\n")], { type: "text/markdown;charset=utf-8" });
  const a = el("a", { href: URL.createObjectURL(blob), download: `${doc.title.slice(0, 40)}·阅读笔记.md` });
  a.click();
  URL.revokeObjectURL(a.href);
  toast("✓ 笔记已导出");
}

/* ---------- AI ---------- */

async function aiStatus() {
  try {
    const s = await api.aiStatus();
    aiOn = s.configured;
    if (!aiOn) $("#ai-btn").title = "未配置 API Key（复制 .env.example 为 .env 并填写），AI 功能不可用";
  } catch { /* 默认关闭 */ }
}

$("#ai-btn").addEventListener("click", async () => {
  if (!aiOn) return toast("未配置 AI：请将 .env.example 复制为 .env 并填入 API Key", "error", 3600);
  openModal("✦ AI 摘要", (body, close) => {
    body.append(el("div", { class: "loading" }, el("span", { class: "spin" }), "正在阅读全文并生成摘要…"));
    api.aiSummarize(docId).then((r) => {
      body.replaceChildren(el("div", {}, r.summary));
      if (r.cached) toast("展示缓存摘要");
    }).catch((e) => {
      body.replaceChildren(el("div", { class: "muted" }, e.message));
    });
  });
});

function explainSelection(text) {
  const context = doc.blocks.map((b) => b.text).join("\n").slice(0, 4000);
  openModal("✦ 解释选中内容", (body) => {
    body.replaceChildren(
      el("div", { class: "muted small", style: "margin-bottom:10px;font-family:var(--sans)" }, `「${text.slice(0, 60)}${text.length > 60 ? "…" : ""}」`),
      el("div", { class: "loading" }, el("span", { class: "spin" }), "思考中…"));
    api.aiExplain(text, context).then((r) => {
      body.replaceChildren(
        el("div", { class: "muted small", style: "margin-bottom:10px;font-family:var(--sans)" }, `「${text.slice(0, 60)}${text.length > 60 ? "…" : ""}」`),
        el("div", {}, r.explanation));
    }).catch((e) => body.replaceChildren(el("div", { class: "muted" }, e.message)));
  });
}

function openModal(title, fill) {
  const body = el("div", { class: "modal-body ai-modal" });
  const modal = el("div", { class: "modal" },
    el("div", { class: "modal-head" }, el("h3", {}, title),
      el("button", { class: "modal-close", onclick: close }, "✕")),
    body);
  function close() { mask.remove(); }
  const mask = el("div", { class: "modal-mask", onclick: (ev) => { if (ev.target === mask) close(); } }, modal);
  document.body.append(mask);
  fill(body, close);
}

load();
