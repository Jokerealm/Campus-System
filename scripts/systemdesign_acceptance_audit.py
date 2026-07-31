from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from zipfile import ZipFile
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
P3_BACKEND = ROOT / "campus_p3" / "backend"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(P3_BACKEND))

os.environ.setdefault("P3_DATABASE_ENGINE", "sqlite")
os.environ.setdefault("P3_SQLITE_PATH", str(ROOT / "data" / "p3_demo.sqlite3"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")


MANUAL_KEY_PHRASES = [
    "Excel 阅卷统计解析",
    "Word 试卷题目拆分",
    "教师校正和知识点确认",
    "班级考试诊断",
    "Word 讲评教案生成",
    "按薄弱知识点检索题库推荐题",
    "教师可以完整走通“创建考试、上传文件、确认题目、生成报告、下载教案”",
    "当 P1 返回异常或低置信度时，页面必须提示教师处理",
    "诊断报告中必须标明知识点覆盖率",
    "AI 生成内容不得直接发布给学生，必须进入教师审核流程",
    "文件访问必须通过鉴权接口，不直接暴露本地磁盘路径",
]

P1_REQUIRED_ROUTES = [
    ("POST", "/api/ai/v1/parse/score-excel"),
    ("GET", "/api/ai/v1/parse/score-excel/{job_id}/result"),
    ("POST", "/api/ai/v1/parse/paper"),
    ("GET", "/api/ai/v1/parse/paper/{job_id}/result"),
    ("GET", "/api/ai/v1/jobs/{job_id}"),
    ("POST", "/api/ai/v1/knowledge/tag"),
    ("POST", "/api/ai/v1/wrong-question/recognize"),
    ("GET", "/api/ai/v1/wrong-question/recognize/{job_id}/result"),
    ("POST", "/api/ai/v1/explanations/guided/next"),
    ("POST", "/api/ai/v1/questions/variants/generate"),
]

P2_REQUIRED_ROUTES = [
    ("POST", "/exams"),
    ("GET", "/exams"),
    ("GET", "/exams/{exam_id}"),
    ("POST", "/exams/{exam_id}/files"),
    ("POST", "/exams/{exam_id}/parse"),
    ("GET", "/exams/{exam_id}/structure"),
    ("GET", "/exams/{exam_id}/analysis"),
    ("PUT", "/exams/{exam_id}/questions/{exam_question_id}"),
    ("PUT", "/exams/{exam_id}/questions/{exam_question_id}/knowledge-tags"),
    ("POST", "/exams/{exam_id}/diagnostics/run"),
    ("GET", "/exams/{exam_id}/diagnostics/{diagnostic_id}"),
    ("POST", "/exams/{exam_id}/practice-packs"),
    ("POST", "/exams/{exam_id}/lesson-plans"),
    ("GET", "/ai-generated-questions"),
    ("POST", "/ai-generated-questions"),
    ("PUT", "/ai-generated-questions/{generated_question_id}/review"),
    ("GET", "/audit-logs"),
]

P3_RESOURCE_PATTERNS = [
    "knowledge-points",
    "questions/search",
    "questions/import",
    "practice-packs",
    "generated-questions",
    "generated-questions/<str:generated_question_id>/review",
    "stats",
]

P3_STUDENT_PATTERNS = [
    "wrong-questions",
    "wrong-questions/<str:wrong_question_id>",
    "wrong-questions/<str:wrong_question_id>/confirm",
    "wrong-questions/<str:wrong_question_id>/explanation/next",
    "practice/recommendations",
    "practice/answers",
    "practice/progress",
    "practice/answers/history",
    "reports/personal",
]

CONTRACT_FIELDS = {
    "QuestionAnalysis": {"images", "parse_confidence", "needs_review", "confirmed_knowledge_points"},
    "P2ExamAnalysis": {"knowledge_tag_coverage", "practice_recommendations", "practice_packs"},
}


def main() -> None:
    args = parse_args()
    checks: list[dict] = []

    manual_path = resolve_manual_path(args.manual)
    if manual_path:
        manual_text = extract_docx_text(manual_path)
        for index, phrase in enumerate(MANUAL_KEY_PHRASES, start=1):
            add_check(
                checks,
                key=f"manual:first-phase-{index:02d}",
                passed=phrase in manual_text,
                evidence=str(manual_path),
                detail=phrase,
            )
    elif args.allow_missing_manual:
        add_check(
            checks,
            key="manual:external-docx",
            passed=True,
            evidence="manual docx not present in this checkout; embedded v0.1 acceptance matrix used",
            detail="systemdesign.docx is checked when present locally",
        )
    else:
        add_check(
            checks,
            key="manual:external-docx",
            passed=False,
            evidence="missing",
            detail="systemdesign.docx not found; pass --manual or --allow-missing-manual",
        )

    audit_fastapi_routes(checks)
    audit_contract_fields(checks)
    audit_p3_urls(checks)
    audit_dataset(checks, args)
    audit_docs_and_frontend(checks)

    failures = [item for item in checks if not item["passed"]]
    print("systemdesign acceptance audit")
    for item in checks:
        status = "PASS" if item["passed"] else "FAIL"
        print(f"{status} {item['key']}: {item['evidence']}")
    print(f"checks={len(checks)}")
    print(f"failures={len(failures)}")
    if failures:
        print("failed_checks=" + ", ".join(item["key"] for item in failures))
        raise SystemExit("systemdesign acceptance audit failed")
    print("systemdesign acceptance audit passed")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit Campus-System against systemdesign.docx first-phase acceptance.")
    parser.add_argument("--manual", type=Path, default=None, help="Path to systemdesign.docx.")
    parser.add_argument(
        "--allow-missing-manual",
        action="store_true",
        help="Allow CI/checkouts without the external Word manual, while still auditing embedded acceptance items.",
    )
    parser.add_argument("--p1-source", type=Path, default=ROOT / "campus_p1" / "web_app" / "backend" / "papers")
    parser.add_argument("--knowledge-version", default="2026.1")
    parser.add_argument("--min-papers", type=int, default=50)
    parser.add_argument("--min-questions", type=int, default=1_200)
    parser.add_argument("--min-knowledge-points", type=int, default=300)
    return parser.parse_args()


def resolve_manual_path(manual: Path | None) -> Path | None:
    candidates = []
    if manual:
        candidates.append(manual)
    candidates.extend(
        [
            ROOT / "systemdesign.docx",
            ROOT.parent / "systemdesign.docx",
            Path.home() / "Desktop" / "CS224N" / "systemdesign.docx",
        ]
    )
    for path in candidates:
        resolved = path if path.is_absolute() else ROOT / path
        if resolved.exists():
            return resolved
    return None


def extract_docx_text(path: Path) -> str:
    with ZipFile(path) as package:
        xml = package.read("word/document.xml")
    root = ET.fromstring(xml)
    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs = []
    for paragraph in root.findall(".//w:p", namespace):
        text = "".join(node.text or "" for node in paragraph.findall(".//w:t", namespace)).strip()
        if text:
            paragraphs.append(text)
    return "\n".join(paragraphs)


def audit_fastapi_routes(checks: list[dict]) -> None:
    from app.main import P1_PAPER_SUFFIXES, P2_PAPER_SUFFIXES, app

    routes = {
        (method, route.path)
        for route in app.routes
        for method in getattr(route, "methods", set())
        if method not in {"HEAD", "OPTIONS"}
    }
    for method, path in [*P1_REQUIRED_ROUTES, *P2_REQUIRED_ROUTES]:
        add_check(
            checks,
            key=f"route:{method} {path}",
            passed=(method, path) in routes,
            evidence="present" if (method, path) in routes else "missing",
            detail="systemdesign first-phase route",
        )
    add_check(
        checks,
        key="p1:word-only-paper-input",
        passed=P1_PAPER_SUFFIXES == {".docx"},
        evidence=f"P1_PAPER_SUFFIXES={sorted(P1_PAPER_SUFFIXES)}",
        detail="current customer-facing cutter path is Word",
    )
    add_check(
        checks,
        key="p2:paper-upload-suffixes",
        passed=P2_PAPER_SUFFIXES == {".docx", ".json"},
        evidence=f"P2_PAPER_SUFFIXES={sorted(P2_PAPER_SUFFIXES)}",
        detail="standard exam upload accepts Word and normalized JSON fallback",
    )


def audit_contract_fields(checks: list[dict]) -> None:
    from campus_p2.contracts.p2 import P2ExamAnalysis, QuestionAnalysis

    model_fields = {
        "QuestionAnalysis": set(QuestionAnalysis.model_fields),
        "P2ExamAnalysis": set(P2ExamAnalysis.model_fields),
    }
    for model_name, expected_fields in CONTRACT_FIELDS.items():
        missing = expected_fields - model_fields[model_name]
        add_check(
            checks,
            key=f"contract:{model_name}",
            passed=not missing,
            evidence="fields=" + ",".join(sorted(expected_fields - missing)),
            detail="missing=" + ",".join(sorted(missing)) if missing else "all required fields present",
        )


def audit_p3_urls(checks: list[dict]) -> None:
    import django

    django.setup()
    from resources.urls import urlpatterns as resource_patterns
    from students.urls import urlpatterns as student_patterns

    resource_routes = {str(pattern.pattern) for pattern in resource_patterns}
    student_routes = {str(pattern.pattern) for pattern in student_patterns}
    for pattern in P3_RESOURCE_PATTERNS:
        add_check(
            checks,
            key=f"p3-resource:{pattern}",
            passed=pattern in resource_routes,
            evidence="present" if pattern in resource_routes else f"available={sorted(resource_routes)}",
            detail="resource-student API protocol",
        )
    for pattern in P3_STUDENT_PATTERNS:
        add_check(
            checks,
            key=f"p3-student:{pattern}",
            passed=pattern in student_routes,
            evidence="present" if pattern in student_routes else f"available={sorted(student_routes)}",
            detail="student training API protocol",
        )


def audit_dataset(checks: list[dict], args: argparse.Namespace) -> None:
    from resources.management.commands.import_p1_papers_to_bank import _bank_question_id
    from resources.models import KnowledgePoint, QuestionBankItem

    source = args.p1_source if args.p1_source.is_absolute() else ROOT / args.p1_source
    paper_paths = sorted(source.rglob("paper.json"))
    expected_question_ids = []
    image_count = 0
    for path in paper_paths:
        paper = json.loads(path.read_text(encoding="utf-8"))
        paper_id = paper.get("paper_id") or path.parent.name
        for question in paper.get("questions", []):
            expected_question_ids.append(_bank_question_id(paper_id, question))
            image_count += len(question.get("images") or [])

    imported_ids = set(
        QuestionBankItem.objects.filter(
            bank_question_id__in=expected_question_ids,
            knowledge_point_version=args.knowledge_version,
            source=QuestionBankItem.Source.MIDDLE_EXAM_REAL,
        ).values_list("bank_question_id", flat=True)
    )
    questions_with_knowledge = QuestionBankItem.objects.filter(
        bank_question_id__in=expected_question_ids,
        knowledge_point_version=args.knowledge_version,
        source=QuestionBankItem.Source.MIDDLE_EXAM_REAL,
        knowledge_points__isnull=False,
    ).distinct().count()
    knowledge_count = KnowledgePoint.objects.filter(version=args.knowledge_version, enabled=True).count()
    approved_question_count = QuestionBankItem.objects.filter(
        knowledge_point_version=args.knowledge_version,
        audit_status=QuestionBankItem.AuditStatus.APPROVED,
    ).count()

    add_check(
        checks,
        key="dataset:p1-paper-count",
        passed=len(paper_paths) >= args.min_papers,
        evidence=f"papers={len(paper_paths)} source={source}",
        detail=f"min={args.min_papers}",
    )
    add_check(
        checks,
        key="dataset:p1-question-count",
        passed=len(expected_question_ids) >= args.min_questions,
        evidence=f"questions={len(expected_question_ids)} images={image_count}",
        detail=f"min={args.min_questions}",
    )
    add_check(
        checks,
        key="dataset:p3-imported-questions",
        passed=len(imported_ids) == len(expected_question_ids) and bool(expected_question_ids),
        evidence=f"imported={len(imported_ids)} expected={len(expected_question_ids)}",
        detail="50-set P1 outputs imported into P3 middle_exam_real bank",
    )
    add_check(
        checks,
        key="dataset:p3-question-knowledge",
        passed=questions_with_knowledge == len(expected_question_ids) and bool(expected_question_ids),
        evidence=f"with_knowledge={questions_with_knowledge} expected={len(expected_question_ids)}",
        detail="every imported question has at least one P3 knowledge point",
    )
    add_check(
        checks,
        key="dataset:p3-knowledge-count",
        passed=knowledge_count >= args.min_knowledge_points,
        evidence=f"knowledge_points={knowledge_count}",
        detail=f"min={args.min_knowledge_points}",
    )
    add_check(
        checks,
        key="dataset:p3-approved-question-count",
        passed=approved_question_count >= args.min_questions,
        evidence=f"approved_questions={approved_question_count}",
        detail=f"min={args.min_questions}",
    )


def audit_docs_and_frontend(checks: list[dict]) -> None:
    frontend = (ROOT / "frontend" / "src" / "main.tsx").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    audit_doc = ROOT / "docs" / "systemdesign_implementation_audit.md"
    demo_image = ROOT / "docs" / "p2_demo.jpeg"
    add_check(
        checks,
        key="frontend:customer-word-upload",
        passed='accept=".docx"' in frontend and "预览分析效果" not in frontend and "delivery-card" in frontend,
        evidence="teacher upload accepts .docx; internal preview button removed; customer delivery card exists",
        detail="default teacher surface is Word-only and customer-facing",
    )
    add_check(
        checks,
        key="frontend:admin-gated",
        passed="adminMode ? <ReleaseStrip" in frontend and 'section id="audit"' in frontend,
        evidence="admin-only readiness/audit sections are gated",
        detail="customer page hides engineering/admin surfaces",
    )
    add_check(
        checks,
        key="docs:readme-customer-page",
        passed=all(
            phrase in readme
            for phrase in [
                "页面展示",
                "Word 试卷 + 成绩表",
                "推荐会随知识点和失分率刷新",
                "导出 Word",
            ]
        ),
        evidence="README page section updated",
        detail="delivery docs describe customer-facing UI",
    )
    add_check(
        checks,
        key="docs:systemdesign-audit",
        passed=audit_doc.exists(),
        evidence=str(audit_doc),
        detail="manual implementation audit document exists",
    )
    add_check(
        checks,
        key="docs:p2-demo-image",
        passed=demo_image.exists() and demo_image.stat().st_size > 50_000,
        evidence=f"{demo_image} size={demo_image.stat().st_size if demo_image.exists() else 0}",
        detail="README screenshot artifact exists",
    )


def add_check(checks: list[dict], *, key: str, passed: bool, evidence: str, detail: str) -> None:
    checks.append({"key": key, "passed": passed, "evidence": evidence, "detail": detail})


if __name__ == "__main__":
    main()
