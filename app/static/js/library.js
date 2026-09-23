/* 文献库页：列表、筛选、全文检索、导入、元数据编辑与引用复制 */
import { $, $$, el, esc, toast, debounce, initTheme, SRC_LABEL } from "./common.js";
import { api, apiErr } from "./api.js";
import { gbt7714 } from "./citation.js";

const PRESET_TAGS = ["民法", "刑法", "行政法", "商法", "知识产权法", "国际法", "诉讼法", "宪法", "法理学", "法制史", "计算法学"];

const state = { filter: "all", tag: "", q: "", docs: [], tags: [] };

initTheme("#theme-toggle");

/* ---------- 渲染 ---------- */

async function refresh() {
  try {
    const [docs, tags, stats] = await Promise.all([
      api.listDocs(state.filter === "starred" ? { starred: 1 } : {}),
      api.tags(),
      api.stats(),
    ]);
    state.docs = docs;
    state.tags = tags;
    renderSidebar(tags, stats);
    if (state.q.trim()) renderSearch(state.q);
    else renderCards(filterByTag(docs));
  } catch (e) { apiErr(e); }
}

function filterByTag(docs) {
  return state.tag ? docs.filter((d) => d.tags.includes(state.tag)) : docs;
}

function renderSidebar(tags, stats) {
  $("#cnt-all").textContent = stats.documents || "";
  $("#tag-list").replaceChildren(
    ...tags.map((t) => el("button", {
      class: `side-item${state.tag === t.name ? " active" : ""}`,
      onclick: () => { state.tag = state.tag === t.name ? "" : t.name; refresh(); },
    }, `# ${esc(t.name)}`, el("span", { class: "count" }, t.count)))
  );
  $("#stats").replaceChildren(
    el("div", {}, el("b", {}, stats.documents), el("span", {}, "文献")),
    el("div", {}, el("b", {}, stats.annotations), el("span", {}, "批注")),
    el("div", {}, el("b", {}, stats.finished), el("span", {}, "已读完")),
  );
}

function renderCards(docs) {
  const list = $("#doc-list");
  if (!docs.length) {
    list.replaceChildren(el("div", { class: "empty" },
      el("div", { class: "glyph" }, "⚖"),
      el("h2", {}, state.tag || state.filter === "starred" ? "这里还没有文献" : "欢迎来到律读"),
      el("p", {}, state.tag || state.filter === "starred"
        ? "换个筛选条件，或导入新文献吧"
        : "导入 PDF、Word 或网页链接，开始你的法学文献精读之旅"),
    ));
    return;
  }
  list.replaceChildren(el("div", { class: "doc-grid" }, ...docs.map(docCard)));
}

function docCard(d) {
  const meta = [d.author, d.year, d.publication].filter(Boolean).join(" · ");
  const pct = Math.round((d.progress || 0) * 100);
  return el("article", {
    class: "doc-card",
    onclick: () => { location.href = `/reader.html?id=${d.id}`; },
  },
    el("button", {
      class: `star-btn${d.starred ? " on" : ""}`,
      title: d.starred ? "取消星标" : "加星标",
      onclick: async (ev) => {
        ev.stopPropagation();
        try { await api.patchDoc(d.id, { starred: !d.starred }); refresh(); }
        catch (e) { apiErr(e); }
      },
    }, d.starred ? "★" : "☆"),
    el("div", { class: "head" },
      el("span", { class: `src-badge ${d.source_type}` }, SRC_LABEL[d.source_type] || d.source_type),
      ...d.tags.map((t) => el("span", { class: "chip" }, esc(t))),
      d.statutes.length ? el("span", { class: "chip gold", title: "文中识别到的法条引用" }, `⚖ ${d.statutes.length}`) : null,
    ),
    el("h3", {}, esc(d.title)),
    meta ? el("div", { class: "meta" }, esc(meta)) : null,
    d.snippet ? el("div", { class: "snippet" }, esc(d.snippet)) : null,
    el("div", { class: "foot" },
      el("span", {}, `${d.word_count || 0} 字`),
      d.ann_count ? el("span", {}, `✎ ${d.ann_count}`) : null,
      el("div", { class: "progress-track", title: `阅读进度 ${pct}%` },
        el("div", { class: "progress-fill", style: `width:${pct}%` })),
      el("span", {}, `${pct}%`),
      el("span", { class: "spacer" }),
      el("button", {
        class: "btn icon", title: "编辑信息 / 引用",
        onclick: (ev) => { ev.stopPropagation(); openMetaModal(d.id); },
      }, "✎"),
      el("button", {
        class: "btn icon danger", title: "删除",
        onclick: async (ev) => {
          ev.stopPropagation();
          if (!confirm(`确定删除《${d.title}》？批注将一并删除。`)) return;
          try { await api.delDoc(d.id); toast("已删除"); refresh(); }
          catch (e) { apiErr(e); }
        },
      }, "🗑"),
    ),
  );
}

/* ---------- 全文检索 ---------- */

async function renderSearch(q) {
  const list = $("#doc-list");
  list.replaceChildren(el("div", { class: "muted small", style: "padding:4px 2px 14px" },
    `「${q}」的检索结果…`));
  try {
    const hits = await api.search(q);
    if (!hits.length) {
      list.append(el("div", { class: "empty" },
        el("div", { class: "glyph" }, "∅"), el("h2", {}, "没有找到"), el("p", {}, "标题、正文与批注中均无匹配")));
      return;
    }
    list.append(el("div", { class: "search-results", id: "hits" },
      ...hits.map((h) => el("div", {
        class: "hit",
        onclick: () => { location.href = `/reader.html?id=${h.doc_id}${h.block_id ? `&goto=${h.block_id}` : ""}`; },
      },
        el("div", { class: "t" },
          el("span", { class: `src-badge ${h.source_type}` }, SRC_LABEL[h.source_type] || ""),
          esc(h.title)),
        el("div", { class: "s" }, el("span", { class: "badge", style: "margin-right:6px" }, h.field),
          el("span", { html: highlight(h.snippet, q) })),
      ))));
  } catch (e) { apiErr(e); }
}

function highlight(snippet, q) {
  const idx = snippet.indexOf(q);
  if (idx < 0) return esc(snippet);
  return esc(snippet.slice(0, idx)) + "<mark>" + esc(q) + "</mark>" + esc(snippet.slice(idx + q.length));
}

/* ---------- 导入弹窗 ---------- */

function openImportModal() {
  const fileInput = el("input", { type: "file", accept: ".pdf,.docx", multiple: true });
  const drop = el("div", { class: "dropzone" },
    el("div", { class: "big" }, "点击选择或拖入文件"),
    el("div", {}, "支持 PDF（文字版）与 Word .docx"), fileInput);
  drop.onclick = () => fileInput.click();
  drop.ondragover = (ev) => { ev.preventDefault(); drop.classList.add("over"); };
  drop.ondragleave = () => drop.classList.remove("over");
  drop.ondrop = (ev) => {
    ev.preventDefault();
    drop.classList.remove("over");
    handleFiles([...ev.dataTransfer.files]);
  };
  fileInput.onchange = () => handleFiles([...fileInput.files]);

  const urlInput = el("input", { placeholder: "https://…（法学论文页、微信公众号文章等）",
    style: "width:100%;padding:9px 12px;border:1px solid var(--line);border-radius:6px;outline:none;background:var(--paper)" });
  const urlBtn = el("button", { class: "btn primary", onclick: doImportUrl }, "抓取正文");
  const textTitle = el("input", { placeholder: "标题（可留空，取首行）",
    style: "width:100%;padding:9px 12px;border:1px solid var(--line);border-radius:6px;outline:none;background:var(--paper)" });
  const textArea = el("textarea", { placeholder: "粘贴文献全文。支持轻量约定：空行分段，行首 # ## ### 为标题，> 为引用",
    style: "width:100%;min-height:200px;padding:9px 12px;border:1px solid var(--line);border-radius:6px;outline:none;background:var(--paper);resize:vertical;font-size:13.5px" });
  const textBtn = el("button", { class: "btn primary", onclick: doImportText }, "保存为文献");

  const paneFile = el("div", {}, drop);
  const paneUrl = el("div", { style: "display:flex;flex-direction:column;gap:12px" },
    el("div", { class: "muted small" }, "输入公开可访问的网址，律读会自动抓取并整理正文。"),
    urlInput, el("div", {}, urlBtn));
  const paneText = el("div", { style: "display:flex;flex-direction:column;gap:12px" },
    textTitle, textArea, el("div", {}, textBtn));

  const panes = { file: paneFile, url: paneUrl, text: paneText };
  const tabs = el("div", { class: "tabs" });
  const paneWrap = el("div", {});
  const modal = el("div", { class: "modal" },
    el("div", { class: "modal-head" }, el("h3", {}, "导入文献"),
      el("button", { class: "modal-close", onclick: close }, "✕")),
    el("div", { class: "modal-body" }, tabs, paneWrap));

  const tabDefs = [["file", "📄 上传文件"], ["url", "🔗 网页链接"], ["text", "✎ 粘贴文本"]];
  tabDefs.forEach(([key, label], i) => {
    tabs.append(el("button", {
      class: `tab${i === 0 ? " active" : ""}`,
      onclick: () => {
        $$(".tab", tabs).forEach((t) => t.classList.remove("active"));
        tabs.children[i].classList.add("active");
        paneWrap.replaceChildren(panes[key]);
      },
    }, label));
  });
  paneWrap.replaceChildren(paneFile);

  async function handleFiles(files) {
    const ok = files.filter((f) => /\.(pdf|docx)$/i.test(f.name));
    if (!ok.length) return toast("请选择 .pdf 或 .docx 文件", "error");
    for (const f of ok) {
      toast(`正在解析《${f.name}》…`, "info", 8000);
      try {
        const r = await api.upload(f);
        toast(`✓ 已导入《${r.title}》${r.statutes ? `，识别法条 ${r.statutes} 处` : ""}`);
        refresh();
      } catch (e) { apiErr(e); }
    }
  }

  async function doImportUrl() {
    const url = urlInput.value.trim();
    if (!url) return toast("请输入网址", "error");
    urlBtn.disabled = true;
    urlBtn.textContent = "抓取中…";
    try {
      const r = await api.importUrl(url);
      toast(`✓ 已导入《${r.title}》`);
      close();
      refresh();
    } catch (e) { apiErr(e); }
    finally { urlBtn.disabled = false; urlBtn.textContent = "抓取正文"; }
  }

  async function doImportText() {
    if (!textArea.value.trim()) return toast("内容为空", "error");
    textBtn.disabled = true;
    try {
      const r = await api.importText(textTitle.value.trim(), textArea.value);
      toast(`✓ 已导入《${r.title}》`);
      close();
      refresh();
    } catch (e) { apiErr(e); }
    finally { textBtn.disabled = false; }
  }

  function close() { mask.remove(); }
  const mask = el("div", { class: "modal-mask", onclick: (ev) => { if (ev.target === mask) close(); } }, modal);
  document.body.append(mask);
  urlInput.addEventListener("keydown", (ev) => { if (ev.key === "Enter") doImportUrl(); });
}

/* ---------- 元数据 / 引用弹窗 ---------- */

async function openMetaModal(docId) {
  let doc;
  try { doc = await api.getDoc(docId); } catch (e) { return apiErr(e); }

  const fields = {};
  const input = (key, label, value) => {
    const inp = el("input", { value, style: "width:100%" });
    inp.oninput = () => { fields[key] = inp.value; updateCitation(); };
    fields[key] = value;
    return el("div", { class: "field" }, el("label", {}, label), inp);
  };

  // 标签编辑器
  let tags = [...doc.tags];
  const tagBox = el("div", { class: "tag-editor" });
  const tagInput = el("input", { placeholder: "输入标签后回车" });
  tagInput.onkeydown = (ev) => {
    if (ev.key === "Enter") {
      ev.preventDefault();
      const v = tagInput.value.trim();
      if (v && !tags.includes(v)) { tags.push(v); renderTags(); }
      tagInput.value = "";
    }
  };
  function renderTags() {
    tagBox.replaceChildren(
      ...tags.map((t) => el("span", { class: "chip" }, esc(t),
        el("span", { class: "x", onclick: () => { tags = tags.filter((x) => x !== t); renderTags(); } }, "✕"))),
      tagInput,
    );
    updateCitation();
  }
  renderTags();

  // 引用生成
  const citType = el("select", {},
    el("option", { value: "journal" }, "期刊论文 [J]"),
    el("option", { value: "web" }, "网页/电子文献 [EB/OL]"),
    el("option", { value: "book" }, "专著 [M]"));
  if (doc.source_type === "web") citType.value = "web";
  citType.onchange = updateCitation;
  const citBox = el("div", { class: "citation-box" });
  const copyBtn = el("button", { class: "btn", onclick: async () => {
    try { await navigator.clipboard.writeText(citBox.textContent); toast("✓ 引用已复制到剪贴板"); }
    catch { toast("复制失败，请手动选择复制", "error"); }
  } }, "⧉ 复制引用");

  function citMeta() {
    return { ...fields, title: fields.title ?? doc.title, tags, url: doc.source_url };
  }
  function updateCitation() { citBox.textContent = gbt7714(citMeta(), citType.value); }

  const modal = el("div", { class: "modal" },
    el("div", { class: "modal-head" }, el("h3", {}, "文献信息"), el("button", { class: "modal-close", onclick: close }, "✕")),
    el("div", { class: "modal-body" },
      el("div", { style: "display:flex;flex-direction:column;gap:12px" },
        input("title", "标题", doc.title),
        input("author", "作者（多人用、分隔）", doc.author),
        el("div", { style: "display:grid;grid-template-columns:1fr 1fr;gap:12px" },
          input("year", "年份", doc.year), input("publication", "期刊 / 出处", doc.publication)),
        el("div", { class: "field" }, el("label", {}, "标签"), tagBox,
          el("div", { class: "tag-suggest" },
            ...PRESET_TAGS.filter((t) => !tags.includes(t)).map((t) =>
              el("span", { class: "chip", onclick: () => { tags.push(t); renderTags(); } }, `+ ${t}`)))),
        el("div", { class: "field" }, el("label", {}, "参考文献格式（GB/T 7714—2015）"),
          el("div", { class: "row" }, citType, el("span", { class: "spacer" }), copyBtn)),
        citBox,
        el("div", { class: "row", style: "margin-top:6px" },
          el("span", { class: "spacer" }),
          el("button", { class: "btn primary", onclick: save }, "保存修改")),
      )));

  async function save() {
    try {
      await api.patchDoc(docId, {
        title: fields.title ?? doc.title, author: fields.author ?? doc.author,
        year: fields.year ?? doc.year, publication: fields.publication ?? doc.publication,
        tags,
      });
      toast("✓ 已保存");
      close();
      refresh();
    } catch (e) { apiErr(e); }
  }
  function close() { mask.remove(); }
  updateCitation();
  const mask = el("div", { class: "modal-mask", onclick: (ev) => { if (ev.target === mask) close(); } }, modal);
  document.body.append(mask);
}

/* ---------- 事件绑定 ---------- */

$$(".side-item[data-filter]").forEach((btn) => {
  btn.addEventListener("click", () => {
    $$(".side-item[data-filter]").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    state.filter = btn.dataset.filter;
    refresh();
  });
});

$("#search-input").addEventListener("input", debounce((ev) => {
  state.q = ev.target.value.trim();
  if (state.q) renderSearch(state.q);
  else renderCards(filterByTag(state.docs));
}, 260));
$("#search-input").addEventListener("keydown", (ev) => {
  if (ev.key === "Escape") { ev.target.value = ""; state.q = ""; renderCards(filterByTag(state.docs)); }
});
$("#import-btn").addEventListener("click", openImportModal);

/* AI 状态 */
api.aiStatus().then((s) => {
  const box = $("#ai-status");
  if (s.configured) { box.classList.add("on"); box.title = `已接入 ${s.model}`; box.append(el("span", {}, "已接入")); }
  else { box.title = "未配置 API Key（.env），AI 摘要与解释不可用，其余功能不受影响"; box.append(el("span", {}, "未配置")); }
}).catch(() => {});

refresh();
