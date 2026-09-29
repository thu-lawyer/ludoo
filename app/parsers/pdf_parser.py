"""PDF 解析：PyMuPDF 提取文字，按行几何重建阅读顺序，字号启发式识别标题。

阅读顺序算法（v2）：
- 逐视觉行收集 bbox；
- 页级保守分栏判定：仅当左/右窄行都足够多、窄行占比过半、且两侧行都不越中线时才按两栏处理；
- 两栏页用「宽行分段带」算法：跨中线宽行按 y 序自成一行并切断分栏段，段内先左栏后右栏；
- 单栏页按 (y, x) 自然排序——段首/段尾短行不再被误分到"左栏"导致全文乱序。
"""
from collections import Counter

try:
    import pymupdf as fitz  # PyMuPDF ≥1.24 推荐导入名
except ImportError:  # 兼容旧版
    import fitz

_MID_TOL = 5.0  # 中线容差（pt）


def parse_pdf(file_path: str) -> dict:
    doc = fitz.open(file_path)
    if doc.is_encrypted:
        try:
            doc.authenticate("")
        except Exception:
            pass
        if doc.is_encrypted:
            raise ValueError("PDF 已加密，无法解析")

    n_pages = len(doc)
    all_lines: list[dict] = []  # {text,size,bold,x0,y0,x1,page}
    for pno, page in enumerate(doc):
        raw = []
        for blk in page.get_text("dict")["blocks"]:
            if blk.get("type") != 0:
                continue
            for ln in blk["lines"]:
                spans = [sp for sp in ln["spans"] if sp["text"].strip()]
                if not spans:
                    continue
                text = "".join(sp["text"] for sp in spans).strip()
                if not text:
                    continue
                x0, y0, x1, _ = ln["bbox"]
                raw.append({
                    "text": text,
                    "size": max(round(sp["size"], 1) for sp in spans),
                    "bold": any("Bold" in sp["font"] or "bold" in sp["font"] for sp in spans),
                    "x0": x0, "x1": x1, "y0": y0,
                    "page": pno,
                })
        all_lines.extend(_page_reading_order(raw, page.rect.width))

    total_chars = sum(len(l["text"]) for l in all_lines)
    if total_chars < 80:
        raise ValueError("未能提取到文字（疑似扫描图片型 PDF），请另存为文字版后重试")

    lines = _drop_noise(all_lines, n_pages)
    if not lines:
        raise ValueError("未能提取到有效正文")

    # 正文字号 = 按字符数加权的众数
    size_weight: Counter = Counter()
    for l in lines:
        size_weight[l["size"]] += len(l["text"])
    body_size = size_weight.most_common(1)[0][0]

    # 相邻行合并为段落：字号突增/加粗识别标题；句末标点分段；短行独立（栏目标题）
    blocks: list[dict] = []
    buf_text = ""

    def flush():
        nonlocal buf_text
        t = buf_text.strip()
        if t:
            blocks.append({"type": "p", "text": t})
        buf_text = ""

    for l in lines:
        t = l["text"]
        is_heading = l["size"] >= body_size + 1.2 or (
            l["bold"] and len(t) < 40 and l["size"] >= body_size
        )
        if is_heading:
            flush()
            level = "1" if l["size"] >= body_size + 3 else "2"
            blocks.append({"type": "h" + level, "text": t.strip()})
            continue
        # 短行且非完整句：多为「基本案情」式栏目标题，独立成段
        if len(t) <= 12 and not t.endswith(("。", "！", "？", "，", "；", "：", ",", ";", ":", ".", "!", "?")):
            flush()
            blocks.append({"type": "p", "text": t})
            continue
        if buf_text and not _ends_sentence(buf_text):
            sep_needed = not (
                _is_cjk(buf_text[-1]) or _is_cjk(t[0])
            )
            buf_text += (" " if sep_needed else "") + t
        else:
            # 上一段以句末标点收尾：本行起新段
            flush()
            buf_text = t
    flush()

    title = next((b["text"] for b in blocks if b["type"] in ("h1", "h2")), "")
    return {
        "blocks": blocks,
        "title": title[:100] or "未命名 PDF 文献",
        "source_type": "pdf",
        "meta": {},
    }


def _page_reading_order(raw: list[dict], page_w: float) -> list[dict]:
    """判定单/双栏并返回阅读序。单栏：(y, x)；双栏：宽行分段带 + 段内左后右。"""
    if not raw:
        return []
    mid = page_w / 2
    wide = [l for l in raw if l["x0"] < mid - _MID_TOL and l["x1"] > mid + _MID_TOL]
    left_n = [l for l in raw if l["x1"] <= mid + _MID_TOL and l not in wide]
    right_n = [l for l in raw if l["x0"] >= mid - _MID_TOL and l not in wide]
    narrow_frac = (len(left_n) + len(right_n)) / len(raw)
    is_two_col = (
        len(left_n) >= 3 and len(right_n) >= 3
        and narrow_frac >= 0.5
        and left_n and all(l["x1"] <= mid + _MID_TOL for l in left_n)
        and right_n and all(l["x0"] >= mid - _MID_TOL for l in right_n)
    )
    if not is_two_col:
        return sorted(raw, key=lambda l: (l["y0"], l["x0"]))

    # 宽行分段带算法
    by_y = sorted(raw, key=lambda l: (l["y0"], l["x0"]))
    out: list[dict] = []
    seg_l: list[dict] = []
    seg_r: list[dict] = []

    def flush_seg():
        nonlocal seg_l, seg_r
        out.extend(sorted(seg_l, key=lambda l: (l["y0"], l["x0"])))
        out.extend(sorted(seg_r, key=lambda l: (l["y0"], l["x0"])))
        seg_l, seg_r = [], []

    for l in by_y:
        if l in wide:
            flush_seg()
            out.append(l)
        elif l["x1"] <= mid + _MID_TOL:
            seg_l.append(l)
        else:
            seg_r.append(l)
    flush_seg()
    return out


def _drop_noise(lines: list[dict], n_pages: int) -> list[dict]:
    """过滤页眉/页脚与纯页码、纯标点行。

    页眉/页脚判定：整行完全相同、出现在 ≥50% 页面、长度 ≤50——
    不限制页面位置（侧栏排版的固定标识常出现在页面中部，如「人民法院案例库」）。
    """
    where: dict[str, set[int]] = {}
    for l in lines:
        where.setdefault(l["text"], set()).add(l["page"])
    repeated = {
        t for t, pages in where.items()
        if n_pages >= 3 and len(pages) >= n_pages * 0.5 and len(t) <= 50
    }
    out = []
    for l in lines:
        t = l["text"]
        if t in repeated:
            continue
        if _is_page_number(t):
            continue
        if not _has_content_char(t):
            continue
        out.append(l)
    return out


def _has_content_char(t: str) -> bool:
    """至少含一个中日韩文字、字母或数字（纯标点/装饰行丢弃，保留 ①② 等）。"""
    import re
    return bool(re.search(r"[\u4e00-\u9fffA-Za-z0-9]", t))


def _is_page_number(t: str) -> bool:
    import re
    t = t.strip()
    return bool(re.fullmatch(r"[-—–\s]*\d{1,4}[-—–\s]*|第\s*\d+\s*页|·\s*\d+\s*·", t))


def _ends_sentence(t: str) -> bool:
    return bool(t) and t[-1] in "。！？.!?"


def _is_cjk(ch: str) -> bool:
    return "\u4e00" <= ch <= "\u9fff"
