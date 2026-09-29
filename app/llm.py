"""LLM 客户端：OpenAI 兼容 chat/completions，默认智谱 GLM（.env 配置 key 后启用）。"""
import json
import re

import requests

from . import config


def chat(messages: list[dict], temperature: float = 0.3, max_tokens: int = 1200) -> str:
    if not config.llm_configured():
        raise RuntimeError("未配置 API Key：请将 .env.example 复制为 .env 并填入 ZHIPU_API_KEY")
    resp = requests.post(
        f"{config.LLM_BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {config.LLM_API_KEY}",
                 "Content-Type": "application/json"},
        json={
            "model": config.LLM_MODEL,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        },
        timeout=90,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"].strip()


def summarize(title: str, text: str) -> str:
    """整篇文献摘要（超长截断，个人阅读场景够用）。"""
    body = text[:9000]
    return chat([
        {"role": "system",
         "content": "你是一位法学研究助理，擅长精读中文学术文献与法律文本。"
                    "请用中文输出结构化摘要，包含：研究问题、核心论点、论证思路、"
                    "主要结论与法学意义，总字数控制在 300 字以内。直接输出内容，不要客套。"},
        {"role": "user", "content": f"文献标题：{title}\n\n正文（可能截断）：\n{body}"},
    ], temperature=0.2)


def explain(selection: str, context: str = "") -> str:
    """划选内容解释：术语、法理与制度背景。"""
    ctx = f"\n\n上下文（供参考）：…{context[-1500:]}" if context else ""
    return chat([
        {"role": "system",
         "content": "你是一位法学研究助理。用户会选中一段法律文献中的文字，"
                    "请用中文解释其中的法律术语、法理逻辑与制度背景，"
                    "如涉及法条请说明其规范意旨。200 字以内，直接输出。"},
        {"role": "user", "content": f"选中内容：{selection}{ctx}"},
    ], temperature=0.3, max_tokens=600)


# ---------- 解析质量增强（质检 / 顺序修复 / 元数据提取） ----------

def _extract_json(text: str):
    """从模型输出中稳健提取 JSON（容忍 ```json 围栏与前后杂文）。"""
    for pattern in (r"```(?:json)?\s*(.+?)\s*```", r"(\{.*\}|\[.*\])"):
        m = re.search(pattern, text, re.S)
        if m:
            return json.loads(m.group(1))
    raise ValueError("模型未返回有效 JSON")


def check_doc_quality(title: str, blocks: list[dict], word_count: int) -> dict:
    """解析质量检查：抽样块送检，返回 {score:1-5, issues:[], summary}。"""
    n = len(blocks)
    idx = set(range(min(5, n)))
    if n > 10:
        mid = n // 2
        idx |= {mid - 1, mid, mid + 1, n - 3, n - 2, n - 1}
    idx = sorted(i for i in idx if 0 <= i < n)
    sample = "\n".join(f"块{i}: {blocks[i].get('text', '')[:80]}" for i in idx)
    out = chat([
        {"role": "system",
         "content": "你是文献数字化质检员。以下是从一份文档解析出的文本块抽样（保留原顺序）。"
                    "请检查：1)语句是否连贯 2)有无明显乱序（如前后内容毫无衔接）"
                    "3)有无页眉页脚/页码残留 4)有无明显缺句断档。"
                    '只返回 JSON：{"score": 1到5整数, "issues": ["问题1", ...], '
                    '"summary": "一句话结论"}。无问题时 issues 为空数组。'},
        {"role": "user",
         "content": f"标题：{title}\n全文约 {word_count} 字、共 {n} 块。\n抽样：\n{sample}"},
    ], temperature=0.1, max_tokens=500)
    report = _extract_json(out)
    report["score"] = max(1, min(5, int(report.get("score", 3))))
    report["issues"] = [str(i)[:80] for i in (report.get("issues") or [])][:6]
    report["summary"] = str(report.get("summary") or "")[:120]
    return report


def repair_block_order(blocks: list[dict]) -> list[int]:
    """阅读顺序修复：模型只返回块的排列（不碰文字），返回原索引列表。"""
    if len(blocks) > 80:
        raise ValueError("文本块过多（>80），不建议 AI 修复顺序")
    listing = "\n".join(f"{i}: {b.get('text', '')[:60]}" for i, b in enumerate(blocks))
    out = chat([
        {"role": "system",
         "content": "你是文档阅读顺序修复器。下面是解析出的文本块（编号: 内容开头）。"
                    "部分块的先后顺序可能错乱。请根据内容逻辑判断正确阅读顺序，"
                    "返回 JSON 数组：全部编号的一个排列，如 [0,2,1,3]。"
                    "规则：不得增删或改写任何编号；若原顺序已正确，原样返回；只返回 JSON。"},
        {"role": "user", "content": listing},
    ], temperature=0.1, max_tokens=1200)
    perm = _extract_json(out)
    if (not isinstance(perm, list) or sorted(perm) != list(range(len(blocks)))):
        raise ValueError("模型返回的顺序无效")
    return perm


def extract_meta(text: str) -> dict:
    """从文献开头提取元数据：{author, year, publication, keywords[], abstract}。"""
    out = chat([
        {"role": "system",
         "content": "从文献开头提取元数据。只返回 JSON："
                    '{"author": "作者（多人顿号分隔，没有则空串）", "year": "年份如2023，没有则空串", '
                    '"publication": "期刊或出处，没有则空串", "keywords": ["关键词", ...最多6个], '
                    '"abstract": "50字内概括，没有则空串"}。'},
        {"role": "user", "content": text[:1600]},
    ], temperature=0.1, max_tokens=400)
    meta = _extract_json(out)
    if not isinstance(meta, dict):
        raise ValueError("模型返回的元数据无效")
    return meta
