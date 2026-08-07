"""教学反馈报告编排：excel + paper.json + 模板 -> md / docx / pdf。"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from . import llm_report, template_render
from .schema import (
    ClassReport,
    QuestionStat,
    build_class_report,
    parse_excel,
    qtype_aggregate,
    weak_questions,
)


@dataclass
class BuildResult:
    report_id: str
    md: str
    docx_bytes: bytes | None
    pdf_bytes: bytes | None
    report: ClassReport


def _load_paper_meta(papers_dir: Path, paper_id: str) -> dict:
    p = papers_dir / paper_id / "paper.json"
    return json.loads(p.read_text(encoding="utf-8"))


def _build_paper_question_index(paper: dict) -> dict[str, dict]:
    """题号字符串 -> 该题完整信息（含 qwen_analysis.knowledge_points）。"""
    idx: dict[str, dict] = {}
    for q in paper.get("questions", []):
        idx[str(q.get("question_no"))] = q
        # 也兼容 "21(1)" 这种带括号子题：取前缀数字
    return idx


def _context(
    report: ClassReport,
    paper: dict,
    paper_id: str,
    teacher: str,
    class_name: str,
) -> dict:
    weak = weak_questions(report, top_k=5)
    paper_idx = _build_paper_question_index(paper)

    # 把薄弱题与题目原文/知识点合并
    weak_items: list[dict] = []
    for w in weak:
        meta = paper_idx.get(w.no, {})
        kps = (meta.get("qwen_analysis") or {}).get("knowledge_points") or []
        weak_items.append({
            **w.to_dict(),
            "stem": (meta.get("stem_markdown") or meta.get("stem") or "")[:160],
            "knowledge_points": kps,
            "full_score": w.full_score,
            "avg_score": w.avg_score,
        })

    qtype_rows = qtype_aggregate(report)

    overall = {
        "n_students": report.n_students,
        "total_score": report.total_score,
        "avg_total_score": report.avg_total_score,
        "pass_rate": report.pass_rate,
        "excellent_rate": report.excellent_rate,
    }

    # LLM 生成（服务不可用时返回占位文本，不会阻塞）
    knowledge_md = llm_report.generate_knowledge_analysis(weak_items)
    advice_md = llm_report.generate_teaching_advice(qtype_rows, overall)

    return {
        "paper_id": paper_id,
        "paper_name": report.paper_name,
        "class_name": class_name or "未填写",
        "teacher": teacher or "未填写",
        "date": time.strftime("%Y-%m-%d"),
        "n_students": report.n_students,
        "total_score": report.total_score,
        "avg_total_score": report.avg_total_score,
        "pass_rate": report.pass_rate,
        "excellent_rate": report.excellent_rate,
        "questions": [q.to_dict() for q in report.questions],
        "weak_items": weak_items,
        "qtype_agg": qtype_rows,
        "knowledge_md": knowledge_md,
        "advice_md": advice_md,
        # 直接包含一段「整体表现」markdown，便于模板复用
        "overall_md": _build_overall_md(report),
        # 错题率表格（markdown）
        "questions_table_md": _questions_table_md(report.questions),
    }


def _questions_table_md(qs: list[QuestionStat]) -> str:
    head = "| 题号 | 题型 | 分值 | 班级均分 | 错题率 | 零分率 | 满分率 | 难度 |\n|---|---|---|---|---|---|---|---|"
    rows = [
        f"| 第 {q.no} 题 | {q.qtype or '-'} | {q.full_score} | {q.avg_score} | "
        f"{q.error_rate*100:.1f}% | {q.zero_rate*100:.1f}% | {q.full_rate*100:.1f}% | {q.difficulty or '-'}|"
        for q in qs
    ]
    return head + "\n" + "\n".join(rows)


def _build_overall_md(report) -> str:
    """拼接「整体表现」段落。n_students 为 0 时不输出参考人数。"""
    lines: list[str] = []
    if (report.n_students or 0) > 0:
        lines.append(f"- 参考人数：**{report.n_students}** 人")
    lines.append(f"- 试卷总分：**{report.total_score}** 分")
    lines.append(f"- 班级均分：**{report.avg_total_score}** 分")
    lines.append(f"- 及格率（≥60%）：**{report.pass_rate*100:.1f}%**")
    lines.append(f"- 优秀率（≥85%）：**{report.excellent_rate*100:.1f}%**")
    return "\n".join(lines)


def build(
    paper_id: str,
    paper_name: str,
    excel_path: str,
    md_template_path: str,
    docx_template_path: str | None,
    teacher: str = "",
    class_name: str = "",
    n_students: int = 50,
    papers_dir: Path | None = None,
    on_stage=None,
) -> BuildResult:
    """主入口：excel + paper.json + 模板 -> BuildResult。

    on_stage: 可选回调，签名 (stage: str, percent: int, message: str)。
              stage 取值：parse_excel / build_report / load_paper / render_md
                          / render_docx / render_pdf / done / error
    """
    def _emit(stage: str, pct: int, msg: str = "") -> None:
        if on_stage:
            try:
                on_stage(stage, pct, msg)
            except Exception:
                pass

    _emit("parse_excel", 10, "解析 Excel 阅卷数据")
    questions, class_meta = parse_excel(excel_path)
    if not questions:
        raise ValueError("Excel 未解析到任何题目，请检查表头/数据")

    _emit("build_report", 30, "汇总班级报告")
    report = build_class_report(
        paper_id=paper_id,
        paper_name=paper_name,
        n_students=int(class_meta.get("n_students") or n_students),
        questions=questions,
        n_pass=int(class_meta["n_pass"]) if "n_pass" in class_meta else None,
        n_excellent=int(class_meta["n_excellent"]) if "n_excellent" in class_meta else None,
        total_score=float(class_meta["total_score"]) if "total_score" in class_meta else None,
        avg_total_score=float(class_meta["avg_total_score"]) if "avg_total_score" in class_meta else None,
        pass_rate=float(class_meta["pass_rate"]) if "pass_rate" in class_meta else None,
        excellent_rate=float(class_meta["excellent_rate"]) if "excellent_rate" in class_meta else None,
    )

    _emit("load_paper", 50, "加载试卷元信息")
    if papers_dir is not None:
        paper = _load_paper_meta(papers_dir, paper_id)
    else:
        paper = {"questions": []}

    ctx = _context(report, paper, paper_id, teacher, class_name)

    _emit("render_md", 65, "渲染 Markdown")
    md = template_render.render_markdown(md_template_path, ctx)

    docx_bytes = None
    if docx_template_path and Path(docx_template_path).exists():
        _emit("render_docx", 80, "渲染 Word (docx)")
        try:
            docx_bytes = template_render.render_docx(docx_template_path, ctx)
        except Exception:
            docx_bytes = None

    _emit("render_pdf", 92, "生成 PDF")
    pdf_bytes = None
    try:
        html_body = template_render.markdown_to_html(md)
        html_full = _wrap_html(html_body)
        pdf_bytes = template_render.html_to_pdf(html_full, base_url=str(Path(md_template_path).parent))
    except Exception:
        pdf_bytes = None

    _emit("done", 100, "生成完成")
    return BuildResult(
        report_id=f"rpt_{int(time.time()*1000)}",
        md=md,
        docx_bytes=docx_bytes,
        pdf_bytes=pdf_bytes,
        report=report,
    )


def _wrap_html(body: str) -> str:
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>教学反馈报告</title>
<style>
body {{ font-family: "Noto Sans CJK SC", "Microsoft YaHei", sans-serif; max-width: 800px; margin: 24px auto; line-height: 1.7; color: #222; }}
h1 {{ color: #2c5fc7; border-bottom: 2px solid #2c5fc7; padding-bottom: 8px; }}
h2 {{ color: #2c5fc7; margin-top: 28px; }}
h3 {{ color: #333; margin-top: 18px; }}
table {{ border-collapse: collapse; width: 100%; margin: 12px 0; font-size: 13px; }}
th, td {{ border: 1px solid #ddd; padding: 6px 10px; text-align: left; }}
th {{ background: #f0f4ff; }}
blockquote {{ background: #fff8e1; border-left: 4px solid #ffb300; padding: 8px 12px; margin: 8px 0; }}
code {{ background: #f5f5f5; padding: 1px 5px; border-radius: 3px; }}
</style></head><body>{body}</body></html>"""
