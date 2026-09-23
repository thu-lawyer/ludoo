"""纯文本解析：直接粘贴的文字，支持 # 标题与 > 引用的轻量约定。"""


def parse_text(title: str, text: str) -> dict:
    if not text.strip():
        raise ValueError("内容为空")
    blocks: list[dict] = []
    for para in text.replace("\r\n", "\n").split("\n\n"):
        t = para.strip()
        if not t:
            continue
        if t.startswith("### "):
            blocks.append({"type": "h3", "text": t[4:].strip()})
        elif t.startswith("## "):
            blocks.append({"type": "h2", "text": t[3:].strip()})
        elif t.startswith("# "):
            blocks.append({"type": "h1", "text": t[2:].strip()})
        elif t.startswith(">"):
            blocks.append({"type": "quote", "text": t.lstrip("> ").strip()})
        else:
            blocks.append({"type": "p", "text": t.replace("\n", "")})
    if not blocks:
        raise ValueError("内容为空")
    return {
        "blocks": blocks,
        "title": (title.strip() or blocks[0]["text"])[:100],
        "source_type": "text",
        "meta": {},
    }
