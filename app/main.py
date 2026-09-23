"""律读 LuDoo — 法学文献阅读器 FastAPI 入口。"""
import re
import shutil
import uuid

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
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


# ---------- 导入 ----------

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


@app.post("/api/documents/upload")
def upload_document(file: UploadFile = File(...)):
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
    return {"id": doc_id, "title": doc["title"], "statutes": len(doc["statutes"])}


@app.post("/api/documents/url")
def import_url(body: UrlIn):
    try:
        parsed = parse_url(body.url.strip())
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    except Exception as e:
        raise HTTPException(422, f"网页解析失败：{e}") from e
    doc = _finalize(parsed, source_url=parsed.get("meta", {}).get("source_url", body.url))
    doc_id = database.create_document(doc)
    return {"id": doc_id, "title": doc["title"], "statutes": len(doc["statutes"])}


@app.post("/api/documents/text")
def import_text(body: TextIn):
    try:
        parsed = parse_text(body.title, body.text)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    doc = _finalize(parsed)
    doc_id = database.create_document(doc)
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
