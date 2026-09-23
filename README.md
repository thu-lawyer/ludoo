# 律读 LuDoo · 法学文献阅读器

> 一个为法学学习打造的本地文献阅读器：PDF / Word / 网页链接 / 纯文本统一导入，
> 清爽排版沉浸阅读，法条引用自动识别，四色分类批注，GB/T 7714 引用一键复制，全文检索，可选 AI 辅助。

计算法学方法课程 · 第二次打卡作业

## 快速开始

```bash
./start.sh
```

脚本会自动：创建虚拟环境 → 安装依赖 → 生成演示样例（首次）→ 启动服务 → 打开浏览器。
默认地址 <http://127.0.0.1:8765>（换端口：`LUDOO_PORT=9000 ./start.sh`）。

手动方式：

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8765
```

> 要求 Python 3.10+。数据全部保存在本地 `data/` 目录（SQLite + 上传原件），删掉即重置。

## 功能速览

| 功能 | 说明 |
|---|---|
| 📥 四源导入 | 上传 **PDF**（文字版，兼容双栏期刊）/ **Word .docx**；粘贴**网页链接**自动抓正文（微信文章、新闻均可试）；直接**粘贴文本**（`#` 标题、`>` 引用） |
| 📖 沉浸阅读 | 统一清爽排版（衬线正文、舒适行距）、目录导航、阅读进度记忆、夜间模式、字号调节 |
| ⚖ 法条识别 | 自动识别《民法典》第一千二百五十四条式的法条引用：正文金色虚线标注，侧栏「法条」页去重汇总（全称/简称合并），点击定位 |
| ✎ 四色批注 | 划选文字即出工具条：**重点**（金）/ **质疑**（红）/ **疑问**（青）/ **联想**（紫），可写心得；侧栏筛选、定位，一键导出 Markdown 读书笔记 |
| 📑 标准引用 | 按 GB/T 7714—2015 生成期刊 [J] / 网页 [EB/OL] / 专著 [M] 参考文献，一键复制 |
| 🔍 全文检索 | 标题、正文、批注一并检索，结果带上下文与关键词高亮 |
| ✦ AI 辅助（可选） | 整篇结构化摘要（缓存复用）、划选段落解释术语与法理；未配置时其余功能完全不受影响 |

## AI 配置（可选）

```bash
cp .env.example .env   # 填入 ZHIPU_API_KEY（智谱开放平台，glm-4-flash 免费）
```

重启服务即可。也可在 `.env` 里用 `LLM_BASE_URL` / `LLM_MODEL` 换成任意 OpenAI 兼容服务（DeepSeek、本地 Ollama 等）。密钥只存在本机 `.env`，不会进入代码或数据库。

## 演示数据

`samples/` 内置三篇原创示意文献（运行 `python scripts/make_samples.py` 可重新生成）：

- `论高空抛物致害责任.docx` —— Word 论文样式，含《民法典》第1254条等多处法条引用
- `正当防卫的司法适用.pdf` —— 文字版 PDF，验证字号/标题启发式解析
- `数据合规学习笔记.txt` —— 纯文本 + 轻量标记

## 项目结构

```
├── start.sh                # 一键启动
├── requirements.txt
├── .env.example            # AI 密钥模板
├── PRD.md                  # 产品需求文档
├── 技术设计.md              # 架构与关键实现
├── app/
│   ├── main.py             # FastAPI 入口 + REST API
│   ├── config.py database.py
│   ├── parsers/            # pdf / docx / web / text 四个解析器
│   ├── legal/statute.py    # 法条引用识别
│   ├── llm.py              # OpenAI 兼容客户端
│   └── static/             # 前端（原生 ES Modules + CSS，无构建）
├── scripts/make_samples.py # 演示样例生成
├── samples/                # 演示文献
└── data/                   # 运行时数据（gitignore）
```

## 公网访问

本地服务默认只监听 `127.0.0.1`。想在其他设备（手机、同学电脑）上访问时：

### 方式一：Cloudflare 快速隧道（推荐，无需服务器）

```bash
./expose.sh
```

- 自动建立免费 HTTPS 隧道，输出形如 `https://xxx.trycloudflare.com` 的公网地址
- **地址每次重启会变**；电脑关机/休眠即离线
- 首次运行若 `.env` 未设 `LUDOO_PASSWORD` 口令会强提醒——公网环境务必设置，否则拿到链接的任何人都能读写你的文献库
- 首次访问者输入口令登录一次，浏览器记住 7 天；服务重启后需重新登录

### 方式二：固定网址（需要自有域名）

将域名接入 Cloudflare（免费套餐）后改用命名隧道：`cloudflared tunnel login` → `cloudflared tunnel create ludoo` → 配置 DNS 路由，即可拥有稳定地址、随时启停。

### 方式三：仅局域网（手机在同一 Wi-Fi）

`uvicorn app.main:app --host 0.0.0.0 --port 8765`，手机访问 `http://<电脑IP>:8765`。注意此方式无 HTTPS，且路由器隔离/AP 隔离可能导致无法连通。

> 安全提示：口令（`LUDOO_PASSWORD`）只保存在本机 `.env`；登录会话为 HMAC 签名 Cookie，服务重启即失效。公网部署期间请勿在文献库中存放涉密内容。

## 常见问题

- **导入 PDF 提示"疑似扫描图片型"**：扫描件无文字层，请先用 OCR（如 WPS/ABBYY）转文字版。
- **网页导入失败**：需公开可访问；需登录或纯动态渲染的页面无法抓取。
- **.doc 老格式**：请先用 Word 另存为 .docx。
- **批注跨段落**：v1 批注锚定在单段内，请分段划选。

## 技术栈

FastAPI · PyMuPDF · python-docx · trafilatura · SQLite · 原生 JavaScript（ES Modules）
