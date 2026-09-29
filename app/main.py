"""律读 LuDoo — 法学文献阅读器 FastAPI 入口。"""
import re
import shutil
import uuid

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, database, llm
from . import auth
from .legal.statute import annotate_blocks
from .parsers.docx_parser import parse_docx
from .parsers.pdf_parser import parse_pdf
from .parsers.text_parser import parse_text
from .parsers.web_parser import parse_url

app = FastAPI(title="律读 LuDoo", version="1.1.0")


@app.on_event("startup")
def startup() -> None:
    config.ensure_dirs()
    database.init_db()


# ---------- 登录（LUDOO_PASSWORD 设置后启用） ----------

app.middleware("http")(auth.auth_middleware)


@app.get("/login", include_in_schema=False)
def login_page():
    return auth.login_page()


@app.post("/login", include_in_schema=False)
def login(password: str = Form("")):
    return auth.handle_login(password)


@app.post("/logout", include_in_schema=False)
def logout():
    return auth.logout()


# ---------- 模型 ----------

class UrlIn(BaseModel):
    url: str


class TextIn(BaseModel):
    title: str = ""
    text: str


class DocPatch(BaseModel):
    title: str | None = None
    author: str | None = None
    year: str | None = None
    publication: str | None = None
    tags: list[str] | None = None
    starred: bool | None = None
    progress: float | None = None


class AnnIn(BaseModel):
    type: str                      # 重点 / 质疑 / 疑问 / 联想
    quote: str = ""
    block_id: str = ""
    start: int = 0
    end: int = 0
    comment: str = ""


class AnnPatch(BaseModel):
    type: str | None = None
    comment: str | None = None


class ExplainIn(BaseModel):
    text: str
    context: str = ""


# ---------- 导入（含导入后的 AI 质检+元数据后台任务） ----------

def _finalize(parsed: dict, source_url: str = "", file_path: str = "") -> dict:
    blocks, statutes = annotate_blocks(parsed["blocks"])
    for i, b in enumerate(blocks):
        b["id"] = f"b{i}"
    text_all = "".join(b.get("text", "") for b in blocks)
    meta = parsed.get("meta", {})
    return {
        "title": parsed["title"],
        "source_type": parsed["source_type"],
        "source_url": source_url or meta.get("source_url", ""),
        "file_path": file_path,
        "author": meta.get("author", ""),
        "year": meta.get("year", ""),
        "publication": meta.get("publication", ""),
        "tags": [],
        "blocks": blocks,
        "statutes": statutes,
        "word_count": len(re.sub(r"\s", "", text_all)),
    }


def _ai_postimport(doc_id: int) -> None:
    """导入完成后台执行：AI 质检 + 元数据补全（静默失败，不阻塞导入）。"""
    if not config.llm_configured():
        return
    try:
        doc = database.get_document(doc_id)
        if not doc:
            return
        report = llm.check_doc_quality(doc["title"], doc["blocks"], doc["word_count"])
        report["checked_at"] = database.now()
        fields: dict = {"ai_report": report}
        try:
            meta = llm.extract_meta("\n".join(b.get("text", "") for b in doc["blocks"][:8]))
            report["keywords"] = [str(k)[:12] for k in (meta.get("keywords") or [])][:6]
            if not doc["author"] and meta.get("author"):
                fields["author"] = str(meta["author"])[:60]
            if not doc["year"] and str(meta.get("year") or "").strip()[:4].isdigit():
                fields["year"] = str(meta["year"]).strip()[:4]
            if not doc["publication"] and meta.get("publication"):
                fields["publication"] = str(meta["publication"])[:60]
        except Exception:  # 元数据失败不影响质检结果
            pass
        database.update_document(doc_id, fields)
    except Exception:
        pass


@app.post("/api/documents/upload")
def upload_document(background: BackgroundTasks, file: UploadFile = File(...)):
    name = file.filename or "upload"
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in ("pdf", "docx"):
        raise HTTPException(400, "仅支持 .pdf 与 .docx 文件（.doc 请先另存为 .docx）")
    dest = config.UPLOAD_DIR / f"{uuid.uuid4().hex}.{ext}"
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    try:
        if ext == "pdf":
            parsed = parse_pdf(str(dest))
        else:
            parsed = parse_docx(str(dest))
    except ValueError as e:
        dest.unlink(missing_ok=True)
        raise HTTPException(422, str(e)) from e
    except Exception as e:  # 解析器崩溃也给出可读信息
        dest.unlink(missing_ok=True)
        raise HTTPException(422, f"解析失败：{e}") from e
    doc = _finalize(parsed, file_path=dest.name)
    doc_id = database.create_document(doc)
    background.add_task(_ai_postimport, doc_id)
    return {"id": doc_id, "title": doc["title"], "statutes": len(doc["statutes"])}


@app.post("/api/documents/url")
def import_url(background: BackgroundTasks, body: UrlIn):
    try:
        parsed = parse_url(body.url.strip())
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    except Exception as e:
        raise HTTPException(422, f"网页解析失败：{e}") from e
    doc = _finalize(parsed, source_url=parsed.get("meta", {}).get("source_url", body.url))
    doc_id = database.create_document(doc)
    background.add_task(_ai_postimport, doc_id)
    return {"id": doc_id, "title": doc["title"], "statutes": len(doc["statutes"])}


@app.post("/api/documents/text")
def import_text(background: BackgroundTasks, body: TextIn):
    try:
        parsed = parse_text(body.title, body.text)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    doc = _finalize(parsed)
    doc_id = database.create_document(doc)
    background.add_task(_ai_postimport, doc_id)
    return {"id": doc_id, "title": doc["title"], "statutes": len(doc["statutes"])}


# ---------- 文档 ----------

@app.get("/api/documents")
def list_docs(q: str = "", tag: str = "", starred: int | None = None):
    return database.list_documents(
        q=q.strip(), tag=tag.strip(),
        starred=None if starred is None else bool(starred),
    )


@app.get("/api/documents/{doc_id}")
def get_doc(doc_id: int):
    doc = database.get_document(doc_id)
    if not doc:
        raise HTTPException(404, "文献不存在")
    return doc


@app.patch("/api/documents/{doc_id}")
def patch_doc(doc_id: int, body: DocPatch):
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if "progress" in fields:
        fields["progress"] = max(0.0, min(1.0, fields["progress"]))
    if not database.update_document(doc_id, fields):
        raise HTTPException(404, "文献不存在")
    return {"ok": True}


@app.delete("/api/documents/{doc_id}")
def del_doc(doc_id: int):
    if not database.delete_document(doc_id):
        raise HTTPException(404, "文献不存在")
    return {"ok": True}


@app.get("/api/tags")
def get_tags():
    return database.all_tags()


@app.get("/api/stats")
def get_stats():
    return database.stats()


@app.get("/api/search")
def search(q: str):
    return database.search(q.strip())


# ---------- 批注 ----------

@app.get("/api/documents/{doc_id}/annotations")
def get_annotations(doc_id: int):
    return database.list_annotations(doc_id)


@app.post("/api/documents/{doc_id}/annotations")
def add_annotation(doc_id: int, body: AnnIn):
    if body.type not in ("重点", "质疑", "疑问", "联想"):
        raise HTTPException(400, "批注类型必须是 重点/质疑/疑问/联想")
    if not database.get_document(doc_id):
        raise HTTPException(404, "文献不存在")
    ann_id = database.create_annotation(doc_id, body.model_dump())
    return {"id": ann_id}


@app.patch("/api/annotations/{ann_id}")
def patch_annotation(ann_id: int, body: AnnPatch):
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if not fields or not database.update_annotation(ann_id, fields):
        raise HTTPException(404, "批注不存在")
    return {"ok": True}


@app.delete("/api/annotations/{ann_id}")
def del_annotation(ann_id: int):
    if not database.delete_annotation(ann_id):
        raise HTTPException(404, "批注不存在")
    return {"ok": True}


# ---------- AI ----------

@app.get("/api/ai/status")
def ai_status():
    return {"configured": config.llm_configured(), "model": config.LLM_MODEL}


def _require_llm() -> None:
    if not config.llm_configured():
        raise HTTPException(400, "未配置 API Key：请将 .env.example 复制为 .env 并填入 ZHIPU_API_KEY")


@app.post("/api/documents/{doc_id}/quality-check")
def ai_quality_check(doc_id: int):
    """手动（重）跑解析质检；保留旧关键词。"""
    _require_llm()
    doc = database.get_document(doc_id)
    if not doc:
        raise HTTPException(404, "文献不存在")
    try:
        report = llm.check_doc_quality(doc["title"], doc["blocks"], doc["word_count"])
    except Exception as e:
        raise HTTPException(502, f"质检失败：{e}") from e
    report["checked_at"] = database.now()
    old_kw = (doc.get("ai_report") or {}).get("keywords") or []
    report.setdefault("keywords", old_kw)
    database.update_document(doc_id, {"ai_report": report})
    return report


@app.post("/api/documents/{doc_id}/repair-order")
def ai_repair_order(doc_id: int):
    """AI 修复阅读顺序：只重排块，不改文字；保存原排列可回退。"""
    _require_llm()
    doc = database.get_document(doc_id)
    if not doc:
        raise HTTPException(404, "文献不存在")
    blocks = doc["blocks"]
    if len(blocks) < 3:
        raise HTTPException(400, "文本块过少，无需修复顺序")
    try:
        perm = llm.repair_block_order(blocks)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:
        raise HTTPException(502, f"修复失败：{e}") from e
    if perm == list(range(len(blocks))):
        return {"changed": False, "message": "AI 认为当前顺序正确，未做修改"}
    new_blocks = [blocks[i] for i in perm]
    database.update_document(doc_id, {"blocks": new_blocks, "order_backup": perm})
    return {"changed": True, "backup": perm}


@app.post("/api/documents/{doc_id}/revert-order")
def ai_revert_order(doc_id: int):
    """回退到 AI 修复前的原始块顺序。"""
    doc = database.get_document(doc_id)
    if not doc:
        raise HTTPException(404, "文献不存在")
    backup = doc.get("order_backup")
    blocks = doc["blocks"]
    if not backup or sorted(backup) != list(range(len(blocks))):
        raise HTTPException(404, "没有可回退的顺序记录")
    original = [None] * len(blocks)
    for new_idx, old_idx in enumerate(backup):
        original[old_idx] = blocks[new_idx]
    database.update_document(doc_id, {"blocks": original, "order_backup": None})
    return {"ok": True}


@app.post("/api/documents/{doc_id}/summarize")
def ai_summarize(doc_id: int):
    doc = database.get_document(doc_id)
    if not doc:
        raise HTTPException(404, "文献不存在")
    if doc.get("ai_summary"):
        return {"summary": doc["ai_summary"], "cached": True}
    text = "\n".join(b.get("text", "") for b in doc["blocks"])
    try:
        summary = llm.summarize(doc["title"], text)
    except RuntimeError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:
        raise HTTPException(502, f"模型调用失败：{e}") from e
    database.update_document(doc_id, {"ai_summary": summary})
    return {"summary": summary, "cached": False}


@app.post("/api/ai/explain")
def ai_explain(body: ExplainIn):
    try:
        result = llm.explain(body.text.strip(), body.context)
    except RuntimeError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:
        raise HTTPException(502, f"模型调用失败：{e}") from e
    return {"explanation": result}


# ---------- 静态前端（放在最后，避免遮蔽 /api） ----------

@app.middleware("http")
async def no_cache_static(request, call_next):
    """本地单用户应用：JS/CSS 不缓存，改动刷新即生效。"""
    resp = await call_next(request)
    p = request.url.path
    if p.startswith(("/js/", "/css/")) or p.endswith((".html",)):
        resp.headers["Cache-Control"] = "no-cache"
    return resp


app.mount("/", StaticFiles(directory=config.BASE_DIR / "app" / "static", html=True), name="static")
