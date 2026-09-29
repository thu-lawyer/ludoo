"""用当前解析器就地重析库内文献（PDF/网页），更新正文块与法条清单。

注意：重析会改变块锚点，对应文献的旧批注将被清空（脚本会逐篇报告）。
用法：source .venv/bin/activate && python scripts/reparse.py [--ids 1,2] [--dry]
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, database  # noqa: E402
from app.legal.statute import annotate_blocks  # noqa: E402
from app.parsers.pdf_parser import parse_pdf  # noqa: E402
from app.parsers.web_parser import parse_url  # noqa: E402


def reparse_doc(doc: dict) -> tuple[bool, int, str]:
    """返回 (成功, 清空的批注数, 说明)。"""
    if doc["source_type"] == "pdf":
        src = config.UPLOAD_DIR / doc["file_path"]
        if not doc["file_path"] or not src.exists():
            return False, 0, "原始文件缺失，跳过"
        try:
            parsed = parse_pdf(str(src))
        except Exception as e:
            return False, 0, f"解析失败：{e}"
    elif doc["source_type"] == "web" and doc["source_url"]:
        try:
            parsed = parse_url(doc["source_url"])
        except Exception as e:
            return False, 0, f"重新抓取失败：{e}"
    else:
        return False, 0, "非 PDF/网页来源，跳过"

    blocks, statutes = annotate_blocks(parsed["blocks"])
    for i, b in enumerate(blocks):
        b["id"] = f"b{i}"
    text_all = "".join(b.get("text", "") for b in blocks)
    anns = database.list_annotations(doc["id"])
    with database.get_db() as db:
        db.execute("DELETE FROM annotations WHERE document_id = ?", (doc["id"],))
    database.update_document(doc["id"], {
        "blocks": blocks, "statutes": statutes,
        "word_count": len(re.sub(r"\s", "", text_all)),
        "ai_report": None, "order_backup": None,
    })
    return True, len(anns), f"块数 {len(blocks)} · 法条 {len(statutes)} · 字数 {len(re.sub(r'\\s', '', text_all))}"


def main() -> None:
    args = sys.argv[1:]
    dry = "--dry" in args
    ids = None
    if "--ids" in args:
        ids = [int(x) for x in args[args.index("--ids") + 1].split(",") if x.strip()]

    config.ensure_dirs()
    database.init_db()
    docs = database.list_documents()
    if ids is not None:
        docs = [d for d in docs if d["id"] in ids]
    targets = [d for d in docs if d["source_type"] in ("pdf", "web")]
    print(f"待重析 {len(targets)} 篇（PDF/网页）\n")
    for d in targets:
        doc = database.get_document(d["id"])
        if dry:
            print(f"[dry] 跳过 #{d['id']} {d['title'][:24]}")
            continue
        ok, n_ann, msg = reparse_doc(doc)
        mark = "✓" if ok else "✗"
        ann_note = f"，清空旧批注 {n_ann} 条" if (ok and n_ann) else ""
        print(f"{mark} #{d['id']} {d['title'][:24]} → {msg}{ann_note}")
    print("\n完成。可运行 `python scripts/reparse.py --dry` 预览而不改动。")


if __name__ == "__main__":
    main()
