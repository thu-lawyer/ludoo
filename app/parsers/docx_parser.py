"""Word (.docx) 解析：python-docx，按样式映射标题/正文/引用块。"""
from docx import Document


def parse_docx(file_path: str) -> dict:
    doc = Document(file_path)
    blocks: list[dict] = []
    for p in doc.paragraphs:
        text = p.text.strip()
        if not text:
            continue
        style = (p.style.name or "").lower()
        if style.startswith("heading 1") or style in ("title",):
            blocks.append({"type": "h1", "text": text})
        elif style.startswith("heading 2"):
            blocks.append({"type": "h2", "text": text})
        elif style.startswith("heading 3"):
            blocks.append({"type": "h3", "text": text})
        elif "quote" in style or "intense" in style:
            blocks.append({"type": "quote", "text": text})
        else:
            blocks.append({"type": "p", "text": text})

    if not blocks:
        raise ValueError("文档中没有可提取的文字内容")

    # 元数据：优先取文档属性，其次第一个大标题
    core = doc.core_properties
    title = (core.title or "").strip()
    if not title:
        title = next((b["text"] for b in blocks if b["type"] == "h1"), blocks[0]["text"])
    author = (core.author or "").strip()

    meta = {}
    if author:
        meta["author"] = author
    return {
        "blocks": blocks,
        "title": title[:100],
        "source_type": "docx",
        "meta": meta,
    }
