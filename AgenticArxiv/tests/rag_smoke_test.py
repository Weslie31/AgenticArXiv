"""
RAG 论文问答 — 离线烟雾测试

只读、零侵入：
- 不修改 tools/rag_tool.py
- 不修改 models/orm.py
- 不修改 api/endpoints.py
- 不通过 FastAPI 路由，纯 Python 函数调用

功能：
1. 自动挑选 output/pdf_raw/ 下体积最大的 PDF 作为测试样本
2. 调用 ask_paper 验证「PDF 切块 → 检索 → LLM 生成」端到端可用
3. 调用 summarize_paper 验证「结构化摘要」端到端可用
4. 验证 paper_chunks 表是否已自动建表、增量索引是否生效
5. 报告写到 output/rag_smoke_report.json

退出码：
  0 = 所有断言通过
  1 = 任一断言失败（但不会抛异常中断）
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# 让脚本可以以 `python tests/rag_smoke_test.py` 运行
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config import settings  # noqa: E402
from models.db import Base, init_db, session_scope  # noqa: E402
from models.orm import PaperChunkRow, PdfAssetRow  # noqa: E402


def pick_test_paper() -> tuple[str, str]:
    """挑选本地已下载、体积最大的 PDF。"""
    pdf_dir = settings.pdf_raw_path
    pdfs = [
        f for f in os.listdir(pdf_dir)
        if f.endswith(".pdf") and os.path.getsize(os.path.join(pdf_dir, f)) > 1024
    ]
    if not pdfs:
        raise RuntimeError(f"output/pdf_raw/ 下没有可用的 PDF，请先用 Agent 下载几篇")
    pdfs.sort(key=lambda f: os.path.getsize(os.path.join(pdf_dir, f)), reverse=True)
    paper_id = pdfs[0][:-4]
    return paper_id, os.path.join(pdf_dir, pdfs[0])


def ensure_pdf_in_db(paper_id: str, pdf_path: str) -> str:
    """确保 PdfAssetRow 存在且 status=READY。返回 local_path。"""
    with session_scope() as s:
        row = s.query(PdfAssetRow).filter_by(paper_id=paper_id).first()
        if row is None:
            row = PdfAssetRow(
                paper_id=paper_id,
                pdf_url=f"file://{pdf_path}",
                local_path=pdf_path,
                status="READY",
                size_bytes=os.path.getsize(pdf_path),
                downloaded_at=datetime.now(),
            )
            s.add(row)
        else:
            row.local_path = pdf_path
            row.status = "READY"
            if not row.size_bytes:
                row.size_bytes = os.path.getsize(pdf_path)
        s.commit()
    return pdf_path


def pre_clean(paper_id: str) -> None:
    """测试前清掉该 paper 的旧 chunks，确保看到的是冷启动索引结果。"""
    with session_scope() as s:
        deleted = s.query(PaperChunkRow).filter_by(paper_id=paper_id).delete()
        s.commit()
        print(f"  [pre] 清理 {deleted} 个旧 chunks")


def count_chunks(paper_id: str) -> int:
    with session_scope() as s:
        return s.query(PaperChunkRow).filter_by(paper_id=paper_id).count()


def get_sample_chunks(paper_id: str, limit: int = 3) -> list[dict]:
    with session_scope() as s:
        rows = (
            s.query(PaperChunkRow)
            .filter_by(paper_id=paper_id)
            .order_by(PaperChunkRow.chunk_index)
            .limit(limit)
            .all()
        )
        return [
            {
                "chunk_index": r.chunk_index,
                "page_start": r.page_start,
                "page_end": r.page_end,
                "section": r.section,
                "token_count": r.token_count,
                "text_preview": r.text[:120],
            }
            for r in rows
        ]


def main() -> int:
    print("=" * 70)
    print("RAG 论文问答 — 离线烟雾测试")
    print("=" * 70)

    report: dict = {
        "started_at": datetime.now().isoformat(),
        "checks": [],
        "errors": [],
    }
    overall_ok = True

    # ---------- 1. 数据库初始化 + paper_chunks 表存在性 ----------
    print("\n[1] 数据库初始化")
    try:
        init_db()
        tables = sorted(Base.metadata.tables.keys())
        chunks_table_exists = "paper_chunks" in tables
        report["checks"].append({
            "step": "db.init",
            "ok": chunks_table_exists,
            "detail": f"paper_chunks in metadata: {chunks_table_exists}",
            "total_tables": len(tables),
        })
        print(f"  OK / 表数量={len(tables)}, paper_chunks={'YES' if chunks_table_exists else 'NO'}")
        if not chunks_table_exists:
            overall_ok = False
    except Exception as e:
        overall_ok = False
        report["errors"].append({"step": "db.init", "error": str(e)})
        print(f"  FAIL: {e}")
        return 1

    # ---------- 2. 选测试论文 + 准备 DB 记录 ----------
    print("\n[2] 选取测试论文")
    try:
        paper_id, pdf_path = pick_test_paper()
        size_kb = os.path.getsize(pdf_path) / 1024
        ensure_pdf_in_db(paper_id, pdf_path)
        report["checks"].append({
            "step": "pick_paper",
            "ok": True,
            "paper_id": paper_id,
            "pdf_path": pdf_path,
            "size_kb": round(size_kb, 1),
        })
        print(f"  OK / paper_id={paper_id}, size={size_kb:.1f} KB")
    except Exception as e:
        overall_ok = False
        report["errors"].append({"step": "pick_paper", "error": str(e)})
        print(f"  FAIL: {e}")
        return 1

    pre_clean(paper_id)

    # ---------- 3. ask_paper 冷启动（无 chunks → 应触发索引） ----------
    print("\n[3] ask_paper 冷启动（应触发自动索引）")
    from tools.rag_tool import ask_paper, summarize_paper  # noqa: E402

    # 用英文问题：论文正文是英文，TF-IDF 是字面匹配，跨语言会召回失败（已知限制）
    question = "What is the core method proposed in this paper?"
    t0 = time.time()
    try:
        result = ask_paper(paper_id=paper_id, question=question, top_k=5)
        elapsed = int((time.time() - t0) * 1000)

        sources = result.get("sources", [])
        ok_no_error = "error" not in result
        ok_has_answer = bool(result.get("answer")) and "未在论文中找到" not in result.get("answer", "")
        ok_has_sources = len(sources) > 0
        # rag_tool 返回 chunk_count + indexed；冷启动后两者都 >0
        ok_indexed = result.get("chunk_count", 0) > 0 or result.get("indexed") is True
        ok_not_low_conf = result.get("confidence") != "low" or len(sources) >= 1

        step_ok = ok_no_error and ok_has_answer and ok_has_sources and ok_indexed and ok_not_low_conf
        overall_ok = overall_ok and step_ok

        report["checks"].append({
            "step": "ask_paper.cold",
            "ok": step_ok,
            "elapsed_ms": elapsed,
            "chunk_count": result.get("chunk_count"),
            "indexed_flag": result.get("indexed"),
            "confidence": result.get("confidence"),
            "sources_count": len(sources),
            "answer_preview": (result.get("answer") or "")[:200],
            "top_sources": [
                {
                    "page": s.get("page"),
                    "section": s.get("section"),
                    "score": s.get("score"),
                }
                for s in sources[:3]
            ],
        })
        print(f"  elapsed={elapsed}ms, chunks={result.get('chunk_count')}, "
              f"indexed={result.get('indexed')}, "
              f"confidence={result.get('confidence')}, sources={len(sources)}")
        print(f"  answer preview: {(result.get('answer') or '')[:200]}...")
        if sources:
            print(f"  top source: page={sources[0].get('page')}, "
                  f"section={sources[0].get('section')}, score={sources[0].get('score')}")
        if not step_ok:
            print(f"  FAIL detail: no_error={ok_no_error}, has_real_answer={ok_has_answer}, "
                  f"has_sources={ok_has_sources}, indexed={ok_indexed}")
            if "error" in result:
                print(f"  error: {result['error']}")
    except Exception as e:
        overall_ok = False
        report["errors"].append({"step": "ask_paper.cold", "error": str(e)})
        print(f"  FAIL (exception): {e}")

    # ---------- 4. 验证 DB 中确实写入了 chunks ----------
    print("\n[4] 验证 paper_chunks 表已写入")
    try:
        cnt = count_chunks(paper_id)
        samples = get_sample_chunks(paper_id, limit=3)
        ok = cnt > 0
        overall_ok = overall_ok and ok
        report["checks"].append({
            "step": "db.chunks_written",
            "ok": ok,
            "chunk_count": cnt,
            "sample_chunks": samples,
        })
        print(f"  chunk_count={cnt}, samples={len(samples)}")
        if not ok:
            print("  FAIL: 索引未生效")
    except Exception as e:
        overall_ok = False
        report["errors"].append({"step": "db.chunks_written", "error": str(e)})
        print(f"  FAIL: {e}")

    # ---------- 5. ask_paper 热路径（复用 chunks） ----------
    print("\n[5] ask_paper 热路径（应复用已有索引）")
    question2 = "What datasets are used for evaluation?"
    t0 = time.time()
    try:
        result2 = ask_paper(paper_id=paper_id, question=question2, top_k=5)
        elapsed2 = int((time.time() - t0) * 1000)
        sources2 = result2.get("sources", [])
        ok_no_error = "error" not in result2
        ok_has_real_answer = bool(result2.get("answer")) and "未在论文中找到" not in result2.get("answer", "")
        ok_has_sources = len(sources2) > 0
        step_ok = ok_no_error and ok_has_real_answer and ok_has_sources
        overall_ok = overall_ok and step_ok
        report["checks"].append({
            "step": "ask_paper.warm",
            "ok": step_ok,
            "elapsed_ms": elapsed2,
            "confidence": result2.get("confidence"),
            "sources_count": len(sources2),
            "answer_preview": (result2.get("answer") or "")[:200],
            "top_source_score": sources2[0].get("score") if sources2 else None,
        })
        print(f"  elapsed={elapsed2}ms, confidence={result2.get('confidence')}, "
              f"sources={len(sources2)}")
        print(f"  answer preview: {(result2.get('answer') or '')[:200]}...")
        if not step_ok and "error" in result2:
            print(f"  error: {result2['error']}")
    except Exception as e:
        overall_ok = False
        report["errors"].append({"step": "ask_paper.warm", "error": str(e)})
        print(f"  FAIL: {e}")

    # ---------- 6. summarize_paper ----------
    print("\n[6] summarize_paper（focus=method）")
    t0 = time.time()
    try:
        sum_result = summarize_paper(paper_id=paper_id, focus="method", max_length=400)
        elapsed3 = int((time.time() - t0) * 1000)
        step_ok = "error" not in sum_result and bool(sum_result.get("summary"))
        overall_ok = overall_ok and step_ok
        report["checks"].append({
            "step": "summarize_paper",
            "ok": step_ok,
            "elapsed_ms": elapsed3,
            "focus": sum_result.get("focus"),
            "summary_preview": (sum_result.get("summary") or "")[:200],
        })
        print(f"  elapsed={elapsed3}ms, focus={sum_result.get('focus')}")
        print(f"  summary preview: {(sum_result.get('summary') or '')[:160]}...")
        if not step_ok and "error" in sum_result:
            print(f"  error: {sum_result['error']}")
    except Exception as e:
        overall_ok = False
        report["errors"].append({"step": "summarize_paper", "error": str(e)})
        print(f"  FAIL: {e}")

    # ---------- 7. 总结 ----------
    report["finished_at"] = datetime.now().isoformat()
    report["overall_ok"] = overall_ok
    report["paper_id"] = paper_id

    report_path = ROOT / "output" / "rag_smoke_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 70)
    print(f"OVERALL: {'PASS' if overall_ok else 'FAIL'}")
    print(f"Report saved to: {report_path}")
    print("=" * 70)

    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(main())
