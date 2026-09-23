"""法条引用识别：从文本中匹配《法律名》第x条/编/章/节 等引用并标注。

典型输入：
    《中华人民共和国民法典》第一千二百五十四条
    《民法典》第1043条
    《刑法》第一百三十三条之一
"""
import re

_CN_DIGIT = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
             "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_CN_UNIT = {"十": 10, "百": 100, "千": 1000}

_NUM = r"[0-9一二三四五六七八九十百千零〇两]+"
# 《法律名》第N条（之M）/ 第N编 / 第N章 / 第N节 ；条后可跟 款/项/号 不吞
_STATUTE_RE = re.compile(
    r"《[^《》\n]{2,40}》第" + _NUM + r"(?:条(?:之[一二三四五六七八九十百]+)?|编|章|节)"
)

ARTICLE_UNITS = {"条", "编", "章", "节"}


def cn_to_int(s: str) -> int | None:
    """中文数字（或阿拉伯数字）转 int，失败返回 None。支持 一千二百五十四 / 十五 / 一百零三。"""
    s = s.strip()
    if s.isdigit():
        return int(s)
    total, num = 0, 0
    for ch in s:
        if ch in _CN_DIGIT:
            num = _CN_DIGIT[ch]
        elif ch in _CN_UNIT:
            unit = _CN_UNIT[ch]
            total += (num or 1) * unit
            num = 0
        else:
            return None
    return total + num


def parse_match(m: str) -> dict:
    """把一段引用文本解析为 {law, article_no, article_label}。"""
    law, rest = m.split("》", 1)
    law = law.lstrip("《")
    num_part = re.search(_NUM, rest).group(0)
    unit = re.search(r"(条|编|章|节)", rest).group(1)
    sub = re.search(r"条之([一二三四五六七八九十百]+)", rest)
    no = cn_to_int(num_part)
    label = f"第{num_part}{unit}"
    if sub:
        label += f"之{sub.group(1)}"
    return {"law": law, "article_no": no, "article_label": label}


def _display_law(law: str) -> str:
    return law.replace("中华人民共和国", "") if law.startswith("中华人民共和国") else law


def annotate_blocks(blocks: list[dict]) -> tuple[list[dict], list[dict]]:
    """给每个块的 html 加法条 span，并汇总去重后的法条清单。

    blocks 每项形如 {id, type, text}；返回 (新 blocks，含 html 字段, 法条清单)。
    《民法典》与《中华人民共和国民法典》视为同一部法律合并计数。
    """
    statute_count: dict[str, dict] = {}
    new_blocks = []
    for b in blocks:
        text = b.get("text", "")
        html = ""
        pos = 0
        for m in _STATUTE_RE.finditer(text):
            raw = m.group(0)
            info = parse_match(raw)
            key = f"{_display_law(info['law'])}·{info['article_label']}"
            if key not in statute_count:
                statute_count[key] = {
                    "law": info["law"], "law_short": _display_law(info["law"]),
                    "article_no": info["article_no"], "article_label": info["article_label"],
                    "raw": raw, "count": 0,
                }
            else:
                # 保留更正式的全称（含「中华人民共和国」）
                if info["law"].startswith("中华人民共和国") and not statute_count[key]["law"].startswith("中华人民共和国"):
                    statute_count[key]["law"] = info["law"]
            statute_count[key]["count"] += 1
            html += _esc(text[pos:m.start()])
            html += f'<span class="statute" data-law="{_esc(info["law"])}" ' \
                    f'data-article="{_esc(info["article_label"])}">{_esc(raw)}</span>'
            pos = m.end()
        html += _esc(text[pos:])
        nb = dict(b)
        nb["html"] = html
        new_blocks.append(nb)
    statutes = sorted(statute_count.values(), key=lambda s: (-s["count"], s["law"]))
    return new_blocks, statutes


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
