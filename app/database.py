"""SQLite 数据层：建表、连接与文档/批注的读写。"""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime

from . import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    source_type TEXT NOT NULL,          -- pdf / docx / web / text
    source_url TEXT DEFAULT '',
    file_path TEXT DEFAULT '',
    author TEXT DEFAULT '',
    year TEXT DEFAULT '',
    publication TEXT DEFAULT '',
    tags TEXT DEFAULT '[]',             -- JSON 数组
    starred INTEGER DEFAULT 0,
    blocks TEXT NOT NULL,               -- JSON: [{id,type,text,html}]
    statutes TEXT DEFAULT '[]',          -- JSON: [{law,article_no,article_label,raw,count}]
    word_count INTEGER DEFAULT 0,
    progress REAL DEFAULT 0,
    ai_summary TEXT DEFAULT '',
    created_at TEXT DEFAULT '',
    updated_at TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS annotations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    type TEXT NOT NULL,                 -- 重点 / 质疑 / 疑问 / 联想
    quote TEXT DEFAULT '',
    block_id TEXT DEFAULT '',
    start INTEGER DEFAULT 0,
    end INTEGER DEFAULT 0,
    comment TEXT DEFAULT '',
    created_at TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_annotations_doc ON annotations(document_id);
"""


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


@contextmanager
def get_db():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    config.ensure_dirs()
    with get_db() as db:
        db.executescript(_SCHEMA)


# ---------- 文档 ----------

_DOC_COLUMNS = (
    "id, title, source_type, source_url, file_path, author, year, publication, "
    "tags, starred, blocks, statutes, word_count, progress, ai_summary, created_at, updated_at"
)


def _doc_to_dict(row: sqlite3.Row, with_blocks: bool = True) -> dict:
    d = dict(row)
    d["tags"] = json.loads(d.get("tags") or "[]")
    d["starred"] = bool(d["starred"])
    if with_blocks:
        d["blocks"] = json.loads(d.get("blocks") or "[]")
    else:
        d.pop("blocks", None)
    d["statutes"] = json.loads(d.get("statutes") or "[]")
    return d


def _snippet(blocks_json: str, limit: int = 120) -> str:
    try:
        blocks = json.loads(blocks_json or "[]")
    except json.JSONDecodeError:
        return ""
    parts = [b.get("text", "") for b in blocks if b.get("type") == "p" and b.get("text")]
    text = "".join(parts).strip()
    return text[:limit] + ("…" if len(text) > limit else "")


def list_documents(q: str = "", tag: str = "", starred: bool | None = None) -> list[dict]:
    sql = (
        f"SELECT d.id, d.title, d.source_type, d.source_url, d.author, d.year, d.publication, "
        "d.tags, d.starred, d.statutes, d.word_count, d.progress, d.created_at, d.updated_at, "
        "d.blocks, "
        "(SELECT COUNT(*) FROM annotations a WHERE a.document_id = d.id) AS ann_count "
        "FROM documents d"
    )
    cond, params = [], []
    if q:
        cond.append("(d.title LIKE ? OR d.author LIKE ? OR d.blocks LIKE ?)")
        like = f"%{q}%"
        params += [like, like, like]
    if tag:
        cond.append("d.tags LIKE ?")
        params.append(f'%"{tag}"%')
    if starred is not None:
        cond.append("d.starred = ?")
        params.append(1 if starred else 0)
    if cond:
        sql += " WHERE " + " AND ".join(cond)
    sql += " ORDER BY d.updated_at DESC"
    with get_db() as db:
        rows = db.execute(sql, params).fetchall()
    docs = []
    for r in rows:
        d = _doc_to_dict(r, with_blocks=False)
        d["snippet"] = _snippet(r["blocks"])
        d["ann_count"] = r["ann_count"]
        docs.append(d)
    return docs


def get_document(doc_id: int) -> dict | None:
    with get_db() as db:
        row = db.execute(
            f"SELECT {_DOC_COLUMNS} FROM documents WHERE id = ?", (doc_id,)
        ).fetchone()
    return _doc_to_dict(row) if row else None


def create_document(doc: dict) -> int:
    cols = (
        "title, source_type, source_url, file_path, author, year, publication, "
        "tags, starred, blocks, statutes, word_count, progress, ai_summary, created_at, updated_at"
    )
    vals = (
        doc["title"], doc["source_type"], doc.get("source_url", ""), doc.get("file_path", ""),
        doc.get("author", ""), doc.get("year", ""), doc.get("publication", ""),
        json.dumps(doc.get("tags", []), ensure_ascii=False), 1 if doc.get("starred") else 0,
        json.dumps(doc["blocks"], ensure_ascii=False),
        json.dumps(doc.get("statutes", []), ensure_ascii=False),
        doc.get("word_count", 0), doc.get("progress", 0), doc.get("ai_summary", ""),
        now(), now(),
    )
    with get_db() as db:
        cur = db.execute(
            f"INSERT INTO documents ({cols}) VALUES ({','.join('?' * len(vals))})", vals
        )
        return cur.lastrowid


def update_document(doc_id: int, fields: dict) -> bool:
    if not fields:
        return False
    sets, params = [], []
    for k, v in fields.items():
        if k in ("tags", "blocks", "statutes"):
            v = json.dumps(v, ensure_ascii=False)
        sets.append(f"{k} = ?")
        params.append(v)
    sets.append("updated_at = ?")
    params.append(now())
    params.append(doc_id)
    with get_db() as db:
        cur = db.execute(f"UPDATE documents SET {', '.join(sets)} WHERE id = ?", params)
        return cur.rowcount > 0


def delete_document(doc_id: int) -> bool:
    with get_db() as db:
        cur = db.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
        return cur.rowcount > 0


def all_tags() -> list[dict]:
    with get_db() as db:
        rows = db.execute("SELECT tags FROM documents").fetchall()
    counts: dict[str, int] = {}
    for r in rows:
        for t in json.loads(r["tags"] or "[]"):
            counts[t] = counts.get(t, 0) + 1
    return [{"name": k, "count": v} for k, v in sorted(counts.items(), key=lambda x: -x[1])]


def stats() -> dict:
    with get_db() as db:
        docs = db.execute("SELECT COUNT(*) c FROM documents").fetchone()["c"]
        notes = db.execute("SELECT COUNT(*) c FROM annotations").fetchone()["c"]
        done = db.execute("SELECT COUNT(*) c FROM documents WHERE progress >= 0.9").fetchone()["c"]
    return {"documents": docs, "annotations": notes, "finished": done}


# ---------- 批注 ----------

_ANN_COLUMNS = "id, document_id, type, quote, block_id, start, end, comment, created_at"


def list_annotations(doc_id: int) -> list[dict]:
    with get_db() as db:
        rows = db.execute(
            f"SELECT {_ANN_COLUMNS} FROM annotations WHERE document_id = ? ORDER BY created_at DESC",
            (doc_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def create_annotation(doc_id: int, ann: dict) -> int:
    with get_db() as db:
        cur = db.execute(
            "INSERT INTO annotations (document_id, type, quote, block_id, start, end, comment, created_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (doc_id, ann["type"], ann.get("quote", ""), ann.get("block_id", ""),
             ann.get("start", 0), ann.get("end", 0), ann.get("comment", ""), now()),
        )
        ann_id = cur.lastrowid
        db.execute("UPDATE documents SET updated_at = ? WHERE id = ?", (now(), doc_id))
    return ann_id


def update_annotation(ann_id: int, fields: dict) -> bool:
    sets = ", ".join(f"{k} = ?" for k in fields)
    params = list(fields.values()) + [ann_id]
    with get_db() as db:
        cur = db.execute(f"UPDATE annotations SET {sets} WHERE id = ?", params)
        return cur.rowcount > 0


def delete_annotation(ann_id: int) -> bool:
    with get_db() as db:
        cur = db.execute("DELETE FROM annotations WHERE id = ?", (ann_id,))
        return cur.rowcount > 0


# ---------- 全文检索 ----------

def search(keyword: str, limit: int = 50) -> list[dict]:
    """在标题、正文、批注中做子串检索，返回带上下文片段的结果。"""
    if not keyword.strip():
        return []
    like = f"%{keyword}%"
    results = []
    with get_db() as db:
        for r in db.execute(
            f"SELECT id, title, source_type, blocks FROM documents "
            f"WHERE title LIKE ? OR blocks LIKE ? ORDER BY updated_at DESC", (like, like)
        ).fetchall():
            blocks = json.loads(r["blocks"] or "[]")
            for b in blocks:
                text = b.get("text", "")
                idx = text.find(keyword)
                if idx >= 0:
                    lo, hi = max(0, idx - 40), idx + len(keyword) + 60
                    results.append({
                        "doc_id": r["id"], "title": r["title"], "source_type": r["source_type"],
                        "field": "正文", "block_id": b.get("id", ""),
                        "snippet": ("…" if lo > 0 else "") + text[lo:hi] + ("…" if hi < len(text) else ""),
                    })
                    break  # 每篇正文只取第一条
        for r in db.execute(
            "SELECT a.document_id, a.type, a.quote, a.comment, d.title, d.source_type "
            "FROM annotations a JOIN documents d ON d.id = a.document_id "
            "WHERE a.quote LIKE ? OR a.comment LIKE ?", (like, like)
        ).fetchall():
            hay = r["quote"] if keyword in r["quote"] else r["comment"]
            idx = hay.find(keyword)
            lo, hi = max(0, idx - 40), idx + len(keyword) + 60
            results.append({
                "doc_id": r["document_id"], "title": r["title"], "source_type": r["source_type"],
                "field": f"批注·{r['type']}", "block_id": "",
                "snippet": ("…" if lo > 0 else "") + hay[lo:hi] + ("…" if hi < len(hay) else ""),
            })
    return results[:limit]
