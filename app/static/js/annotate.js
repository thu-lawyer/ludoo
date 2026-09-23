/* 批注核心：选区定位、高亮渲染、浮动工具条 */

export const ANN_TYPES = ["重点", "质疑", "疑问", "联想"];

/** 当前选区信息：仅支持同一段落内，返回 {blockId, start, end, text} 或 null */
export function getSelectionInfo() {
  const sel = window.getSelection();
  if (!sel || sel.rangeCount === 0 || sel.isCollapsed) return null;
  const range = sel.getRangeAt(0);
  const startBlk = closestBlock(range.startContainer);
  const endBlk = closestBlock(range.endContainer);
  if (!startBlk || !endBlk || startBlk !== endBlk) return null;
  const start = offsetInBlock(startBlk, range.startContainer, range.startOffset);
  const end = offsetInBlock(startBlk, range.endContainer, range.endOffset);
  if (start < 0 || end <= start) return null;
  return { blockId: startBlk.id, start, end, text: sel.toString() };
}

function closestBlock(node) {
  let n = node.nodeType === 1 ? node : node.parentNode;
  while (n && n !== document.body) {
    if (n.classList && n.classList.contains("blk")) return n;
    n = n.parentNode;
  }
  return null;
}

/** 边界点在块内文本中的偏移（Range.toString 长度即所见字符数） */
function offsetInBlock(block, node, offset) {
  try {
    const r = document.createRange();
    r.selectNodeContents(block);
    r.setEnd(node, offset);
    return r.toString().length;
  } catch {
    return -1;
  }
}

/** 把一条批注渲染为正文中的 <mark>（可在不重载整文的情况下增量调用） */
export function wrapAnnotation(block, ann) {
  const segs = [];
  const walker = document.createTreeWalker(block, NodeFilter.SHOW_TEXT);
  let pos = 0;
  while (walker.nextNode()) {
    const n = walker.currentNode;
    const len = n.textContent.length;
    if (pos + len > ann.start && pos < ann.end) {
      segs.push({ node: n, rs: Math.max(ann.start - pos, 0), re: Math.min(ann.end - pos, len) });
    }
    pos += len;
    if (pos >= ann.end) break;
  }
  for (const seg of segs) {
    let node = seg.node;
    if (seg.re < node.textContent.length) node.splitText(seg.re);
    if (seg.rs > 0) node = node.splitText(seg.rs);
    const mark = document.createElement("mark");
    mark.className = "hl";
    mark.dataset.type = ann.type;
    mark.dataset.annId = ann.id;
    node.parentNode.insertBefore(mark, node);
    mark.appendChild(node);
  }
}

/** 按文档顺序应用全部批注（加载时调用一次） */
export function applyAnnotations(article, annotations) {
  const byBlock = new Map();
  for (const a of annotations) {
    if (!a.block_id) continue; // 防御：空锚点（历史脏数据）跳过，避免无效选择器
    if (!byBlock.has(a.block_id)) byBlock.set(a.block_id, []);
    byBlock.get(a.block_id).push(a);
  }
  for (const [blockId, list] of byBlock) {
    const block = article.querySelector(`#${CSS.escape(blockId)}`);
    if (!block) continue;
    list.sort((x, y) => y.start - x.start); // 从右往左包，避免影响未处理偏移
    for (const a of list) wrapAnnotation(block, a);
  }
}

/** 与既有批注是否重叠 */
export function overlaps(annotations, blockId, start, end) {
  return annotations.some(
    (a) => a.block_id === blockId && !(end <= a.start || start >= a.end),
  );
}

/* ---------- 浮动工具条 ---------- */

let toolbar = null;

export function hideToolbar() {
  if (toolbar) { toolbar.remove(); toolbar = null; }
}

/**
 * 在选区上方显示工具条。
 * @param actions [{key, label, color?, onPick}]
 */
export function showToolbar(rect, actions) {
  hideToolbar();
  toolbar = document.createElement("div");
  toolbar.className = "sel-toolbar";
  const inner = document.createElement("div");
  inner.style.cssText = "display:flex;align-items:center;gap:2px;position:relative";
  for (const act of actions) {
    if (act.sep) {
      inner.append(Object.assign(document.createElement("span"), { className: "sep" }));
      continue;
    }
    const btn = document.createElement("button");
    btn.style.display = "flex";
    btn.style.alignItems = "center";
    btn.style.gap = "5px";
    if (act.color) {
      const dot = document.createElement("span");
      dot.className = "dot";
      dot.style.background = act.color;
      btn.append(dot);
    }
    btn.append(document.createTextNode(act.label));
    btn.addEventListener("mousedown", (ev) => ev.preventDefault()); // 防止选区丢失
    btn.addEventListener("click", () => { act.onPick(); hideToolbar(); });
    inner.append(btn);
  }
  const arrow = document.createElement("span");
  arrow.className = "arrow";
  inner.append(arrow);
  toolbar.append(inner);
  document.body.append(toolbar);
  const w = toolbar.offsetWidth;
  let x = rect.left + rect.width / 2 - w / 2;
  x = Math.max(10, Math.min(x, window.innerWidth - w - 10));
  let y = rect.top - toolbar.offsetHeight - 8;
  if (y < 8) y = rect.bottom + 12;
  toolbar.style.left = `${x}px`;
  toolbar.style.top = `${y}px`;
  toolbar.style.position = "fixed";
}
