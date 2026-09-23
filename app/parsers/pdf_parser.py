"""PDF 解析：PyMuPDF 提取文字，按字号启发式识别标题，兼容双栏法学期刊排版。"""
from collections import Counter

try:
    import pymupdf as fitz  # PyMuPDF ≥1.24 推荐导入名
except ImportError:  # 兼容旧版
    import fitz


def parse_pdf(file_path: str) -> dict:
    doc = fitz.open(file_path)
    if doc.is_encrypted:
        try:
            doc.authenticate("")
        except Exception:
            pass
        if doc.is_encrypted:
            raise ValueError("PDF 已加密，无法解析")

    lines: list[dict] = []  # {text, size, bold, page}
    header_counter: Counter = Counter()
    n_pages = len(doc)
    for pno, page in enumerate(doc):
        width = page.rect.width
        raw_blocks = []
        for blk in page.get_text("dict")["blocks"]:
            if blk.get("type") != 0:
                continue
            spans = []
            for line in blk["lines"]:
                for sp in line["spans"]:
                    t = sp["text"].strip()
                    if t:
                        spans.append({
                            "text": t, "size": round(sp["size"], 1),
                            "bold": "Bold" in sp["font"] or "bold" in sp["font"],
                            "x0": sp["bbox"][0], "x1": sp["bbox"][2], "y": sp["bbox"][1],
                        })
            if not spans:
                continue
            # 合并同一块内的 span 为一行
            text = "".join(s["text"] for s in spans)
            size = max(s["size"] for s in spans)
            bold = any(s["bold"] for s in spans)
            x0, x1 = spans[0]["x0"], spans[-1]["x1"]
            y = spans[0]["y"]
            raw_blocks.append({"text": text, "size": size, "bold": bold, "x0": x0, "x1": x1, "y": y})
        # 双栏排版：按左右栏分组后按 y 排序再拼接
        mid = width / 2
        left = sorted([b for b in raw_blocks if (b["x0"] + b["x1"]) / 2 < mid], key=lambda b: b["y"])
        right = sorted([b for b in raw_blocks if (b["x0"] + b["x1"]) / 2 >= mid], key=lambda b: b["y"])
        ordered = left + right
        # 记录页眉页脚候选（每页最上/最下块）
        if ordered:
            header_counter[ordered[0]["text"][:30]] += 1
            header_counter[ordered[-1]["text"][:30]] += 1
        for b in ordered:
            lines.append({**b, "page": pno})

    total_chars = sum(len(l["text"]) for l in lines)
    if total_chars < 80:
        raise ValueError("未能提取到文字（疑似扫描图片型 PDF），请另存为文字版后重试")

    # 过滤页眉页脚：出现超过 40% 页面的固定行、纯页码
    noise = {t for t, c in header_counter.items() if n_pages >= 3 and c >= n_pages * 0.4}
    lines = [
        l for l in lines
        if l["text"][:30] not in noise
        and not _is_page_number(l["text"])
        and len(l["text"].strip()) > 1
    ]
    if not lines:
        raise ValueError("未能提取到有效正文")

    # 正文字号 = 出现最多的字号（按字符数加权）
    size_weight: Counter = Counter()
    for l in lines:
        size_weight[l["size"]] += len(l["text"])
    body_size = size_weight.most_common(1)[0][0]

    # 相邻小行合并为段落：字号接近且本行不是标题
    blocks: list[dict] = []
    buf_text, buf_size, buf_bold = "", body_size, False

    def flush():
        nonlocal buf_text
        t = buf_text.strip()
        if not t:
            return
        btype = _block_type(t, buf_size, buf_bold, body_size, blocks)
        blocks.append({"type": btype, "text": t})
        buf_text = ""

    for l in lines:
        is_heading = l["size"] >= body_size + 1.2 or (
            l["bold"] and len(l["text"]) < 40 and l["size"] >= body_size
        )
        if buf_text:
            # 缓冲与新行能否合并为同一段
            same_para = (
                not is_heading and abs(l["size"] - body_size) < 0.8
                and not buf_text.endswith(("。", "！", "？", "：", "；", ".", "!", "?"))
                and not _looks_like_heading(buf_text)
            )
            if same_para:
                # 中文直接拼接，西文补空格
                sep = "" if _is_cjk(buf_text[-1]) or _is_cjk(l["text"][0]) else " "
                buf_text += sep + l["text"]
                continue
            flush()
        if is_heading:
            blocks.append({"type": "h" + ("1" if l["size"] >= body_size + 3 else "2"), "text": l["text"].strip()})
        else:
            buf_text, buf_size, buf_bold = l["text"], l["size"], l["bold"]
    flush()

    blocks = _merge_short_contiguous(blocks)
    title = next((b["text"] for b in blocks if b["type"] in ("h1", "h2")), "")
    return {
        "blocks": blocks,
        "title": title[:100] or "未命名 PDF 文献",
        "source_type": "pdf",
        "meta": {},
    }


def _block_type(text: str, size: float, bold: bool, body: float, prev: list) -> str:
    if size >= body + 3:
        return "h1"
    if size >= body + 1.2 or (bold and len(text) < 40 and size >= body):
        return "h2"
    if text.startswith(("“", '"')) and len(text) > 60:
        return "quote"
    return "p"


def _looks_like_heading(text: str) -> bool:
    t = text.strip()
    return bool(re_match_head(t)) if t else False


def re_match_head(t: str) -> bool:
    import re
    return bool(re.match(r"^[一二三四五六七八九十]+[、.．]|^第[一二三四五六七八九十百]+[章节部分编]|^[（(][一二三四五六七八九十]+[)）]", t))


def _is_page_number(t: str) -> bool:
    import re
    t = t.strip()
    return bool(re.fullmatch(r"[-—–\s]*\d{1,4}[-—–\s]*|第\s*\d+\s*页|·\s*\d+\s*·", t))


def _is_cjk(ch: str) -> bool:
    return "\u4e00" <= ch <= "\u9fff"


def _merge_short_contiguous(blocks: list[dict]) -> list[dict]:
    """把被断开的短段落并入前一段（常见于 PDF 换行破碎）。"""
    out: list[dict] = []
    for b in blocks:
        if (
            out and b["type"] == "p" and out[-1]["type"] == "p"
            and len(out[-1]["text"]) < 15
        ):
            out[-1]["text"] += b["text"]
        else:
            out.append(dict(b))
    return out
