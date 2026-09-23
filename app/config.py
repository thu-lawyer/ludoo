"""全局配置：路径与 LLM 设置（.env 加载）。"""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "ludoo.db"

load_dotenv(BASE_DIR / ".env")

# LLM：默认智谱开放平台（OpenAI 兼容），可经 .env 覆盖为任意兼容服务
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4").rstrip("/")
LLM_MODEL = os.getenv("LLM_MODEL", "glm-4-flash")
LLM_API_KEY = os.getenv("ZHIPU_API_KEY") or os.getenv("LLM_API_KEY") or ""

# 公网访问口令：留空 = 关闭鉴权（纯本地使用）；设置后页面与 API 均需登录
LUDOO_PASSWORD = os.getenv("LUDOO_PASSWORD", "").strip()


def llm_configured() -> bool:
    return bool(LLM_API_KEY)


def ensure_dirs() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
