"""网页解析：抓取 URL 正文（trafilatura 对中文站点与微信公众号文章友好）。"""
import re

import requests
import trafilatura

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def _decoded(resp: requests.Response) -> str:
    """按页面声明的 charset 或自动探测解码（中文站点常不声明，需探测）。"""
    if resp.encoding and resp.encoding.lower() not in ("iso-8859-1", "ascii"):
        return resp.text
    # requests 对未声明 charset 的响应默认按 Latin-1 解码，对中文页面是错的
    try:
        guessed = resp.apparent_encoding or "utf-8"
    except Exception:
        guessed = "utf-8"
    return resp.content.decode(guessed, errors="replace")


def parse_url(url: str) -> dict:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        resp = requests.get(url, headers={"User-Agent": _UA}, timeout=25, allow_redirects=True)
        resp.raise_for_status()
    except requests.RequestException as e:
        raise ValueError(f"网页抓取失败：{e.__class__.__name__}，请检查链接是否可公开访问") from e

    html = _decoded(resp)

    # 正文：markdown 结构（不带元数据头，避免混入 title/url 等杂行）
    downloaded = trafilatura.extract(
        html, output_format="markdown", include_links=False, include_tables=False,
        include_comments=False, url=resp.url, with_metadata=False,
    )
    if not downloaded or len(downloaded.strip()) < 60:
        raise ValueError("未能从该网页提取到正文（可能需要登录或是动态渲染页面）")

    # 元数据走独立接口（trafilatura ≥2.0 返回 Document 对象）
    metadata = trafilatura.bare_extraction(html, url=resp.url, only_with_metadata=False) or {}
    if hasattr(metadata, "as_dict"):
        metadata = metadata.as_dict()
    title = str(metadata.get("title") or "").strip()
    if not title:
        # 回退：从 HTML <title> 提取
        import re
        m = re.search(r"<title[^>]*>([^<]{2,120})</title>", html, re.I)
        title = m.group(1).strip() if m else ""
    if not title:
        title = resp.url.split("//", 1)[-1][:60]
    title = _clean_title(title)[:100]
    author = str(metadata.get("author") or "").strip()
    date = str(metadata.get("date") or "").strip()  # 形如 2024-05-01

    blocks = _markdown_to_blocks(downloaded)
    meta = {"source_url": resp.url}
    if author:
        meta["author"] = author
    if date[:4].isdigit():
        meta["year"] = date[:4]
        meta["publish_date"] = date
    return {
        "blocks": blocks,
        "title": title[:100],
        "source_type": "web",
        "meta": meta,
    }


def _clean_title(t: str) -> str:
    """去掉网页标题尾部的「--栏目--站点」「_站点」式后缀。"""
    import re

    parts = re.split(r"\s*[-–—|]{2,}\s*", t)
    if len(parts) > 1 and all(len(p) <= 12 for p in parts[1:]):
        t = parts[0].strip()
    for sep in ("_", "|", "—", "－"):
        if sep in t:
            segs = [s.strip() for s in t.split(sep)]
            if len(segs) > 1 and all(len(s) <= 15 for s in segs[1:]):
                t = segs[0].strip()
    return t.strip()


_FURNITURE = "订阅|已订阅|已收藏|收藏|小字号|大字号|点击播报|播报本文|本文[，,]?约|切换|朗读|举报|我要留言|相关阅读|延伸阅读"
_FURNITURE_RUN = re.compile(rf"[*·|｜,，\s]*(?:{_FURNITURE})[*·|｜,，\s]*")


def _markdown_to_blocks(md: str) -> list[dict]:
    """把 trafilatura 的 markdown 输出转为结构化块（忽略图片/链接语法与页面家具文字）。"""
    import re

    md = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", md)          # 图片
    md = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", md)      # 链接保留文字
    md = re.sub(r"\*{1,2}([^*\n]{1,12})\*{1,2}", r"\1", md)  # 粗斜体标记
    md = _FURNITURE_RUN.sub(" ", md)                      # 订阅/收藏/字号等页面按钮文字
    md = re.sub(r"[ \t]{2,}", " ", md)
    blocks: list[dict] = []
    for line in md.splitlines():
        t = line.strip()
        if not t or t in ("---", "***") or len(t) <= 2:
            continue
        if t.startswith("###"):
            blocks.append({"type": "h3", "text": t.lstrip("#").strip()})
        elif t.startswith("##"):
            blocks.append({"type": "h2", "text": t.lstrip("#").strip()})
        elif t.startswith("#"):
            blocks.append({"type": "h1", "text": t.lstrip("#").strip()})
        elif t.startswith(">"):
            blocks.append({"type": "quote", "text": t.lstrip("> ").strip()})
        else:
            blocks.append({"type": "p", "text": t})
    return blocks or [{"type": "p", "text": md.strip()[:200]}]
