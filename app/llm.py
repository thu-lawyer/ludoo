"""LLM 客户端：OpenAI 兼容 chat/completions，默认智谱 GLM（.env 配置 key 后启用）。"""
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
