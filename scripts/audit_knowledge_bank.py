from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
P3_BACKEND = ROOT / "campus_p3" / "backend"
sys.path.insert(0, str(P3_BACKEND))

os.environ.setdefault("P3_DATABASE_ENGINE", "sqlite")
os.environ.setdefault("P3_SQLITE_PATH", str(ROOT / "data" / "p3_demo.sqlite3"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402
from django.core.management import call_command  # noqa: E402


def main() -> None:
    args = parse_args()
    django.setup()

    from resources.management.commands.import_p1_papers_to_bank import (  # noqa: WPS433
        _bank_question_id,
        _specific_point_id,
    )
    from resources.models import KnowledgePoint, QuestionBankItem  # noqa: WPS433

    if args.ensure_import:
        call_command("migrate", "--noinput", verbosity=0)
        call_command("load_knowledge_points", verbosity=0)
        call_command("load_question_bank", verbosity=0)
        call_command(
            "import_p1_papers_to_bank",
            source=str(args.source),
            knowledge_version=args.knowledge_version,
            min_specific_frequency=args.min_specific_frequency,
            specific_knowledge_limit=args.specific_knowledge_limit,
            verbosity=0,
        )

    papers = load_papers(args.source)
    expected_questions = []
    qwen_counter: Counter[str] = Counter()
    source_questions_with_qwen = 0
    source_images = 0
    for paper_path, paper in papers:
        paper_id = paper.get("paper_id") or paper_path.parent.name
        for question in paper.get("questions", []):
            qwen_names = qwen_knowledge_names(question)
            if qwen_names:
                source_questions_with_qwen += 1
            qwen_counter.update(qwen_names)
            source_images += len(question.get("images") or [])
            expected_questions.append(
                {
                    "paper_path": paper_path,
                    "paper_id": paper_id,
                    "paper_name": (paper.get("source") or {}).get("name") or paper_path.parent.name,
                    "question_no": str(question.get("question_no") or ""),
                    "bank_question_id": _bank_question_id(paper_id, question),
                    "qwen_names": qwen_names,
                }
            )

    expected_ids = [item["bank_question_id"] for item in expected_questions]
    imported_questions = {
        item.bank_question_id: item
        for item in QuestionBankItem.objects.filter(
            bank_question_id__in=expected_ids,
            knowledge_point_version=args.knowledge_version,
        ).prefetch_related("knowledge_points")
    }
    imported_middle_exam = {
        item.bank_question_id: item
        for item in imported_questions.values()
        if item.source == QuestionBankItem.Source.MIDDLE_EXAM_REAL
    }
    missing_questions = [item for item in expected_questions if item["bank_question_id"] not in imported_questions]
    wrong_source_questions = [
        item
        for item in expected_questions
        if item["bank_question_id"] in imported_questions
        and imported_questions[item["bank_question_id"]].source != QuestionBankItem.Source.MIDDLE_EXAM_REAL
    ]
    no_knowledge_questions = [
        item
        for item in expected_questions
        if item["bank_question_id"] in imported_questions
        and not imported_questions[item["bank_question_id"]].knowledge_points.all()
    ]

    frequent_qwen_names = {
        name for name, count in qwen_counter.items() if count >= args.min_specific_frequency
    }
    expected_specific_ids = {_specific_point_id(name) for name in frequent_qwen_names}
    existing_specific_ids = set(
        KnowledgePoint.objects.filter(
            knowledge_point_id__in=expected_specific_ids,
            version=args.knowledge_version,
            enabled=True,
        ).values_list("knowledge_point_id", flat=True)
    )
    missing_specific_ids = expected_specific_ids - existing_specific_ids

    summary = {
        "source_dir": str(args.source),
        "source_papers": len(papers),
        "source_questions": len(expected_questions),
        "source_images": source_images,
        "source_questions_with_qwen": source_questions_with_qwen,
        "unique_qwen_knowledge_names": len(qwen_counter),
        "frequent_qwen_knowledge_names": len(frequent_qwen_names),
        "db_knowledge_points": KnowledgePoint.objects.filter(version=args.knowledge_version).count(),
        "db_questions": QuestionBankItem.objects.filter(knowledge_point_version=args.knowledge_version).count(),
        "expected_imported_questions": len(expected_questions),
        "imported_questions_found": len(imported_questions),
        "imported_middle_exam_questions": len(imported_middle_exam),
        "questions_with_p3_knowledge": len(expected_questions) - len(no_knowledge_questions),
        "missing_imported_questions": len(missing_questions),
        "wrong_source_questions": len(wrong_source_questions),
        "missing_specific_knowledge_points": len(missing_specific_ids),
        "questions_without_p3_knowledge": len(no_knowledge_questions),
    }
    summary["question_import_coverage"] = ratio(
        summary["imported_questions_found"],
        summary["expected_imported_questions"],
    )
    summary["question_knowledge_coverage"] = ratio(
        summary["questions_with_p3_knowledge"],
        summary["expected_imported_questions"],
    )
    summary["specific_knowledge_coverage"] = ratio(
        len(existing_specific_ids),
        len(expected_specific_ids),
    )

    print("knowledge bank audit")
    for key, value in summary.items():
        print(f"{key}={value}")

    print_samples("missing_imported_question_samples", missing_questions, args.sample_limit)
    print_samples("questions_without_p3_knowledge_samples", no_knowledge_questions, args.sample_limit)
    if missing_specific_ids:
        print("missing_specific_knowledge_point_samples=" + ",".join(sorted(missing_specific_ids)[: args.sample_limit]))

    failures = []
    if summary["source_papers"] < args.min_papers:
        failures.append(f"source_papers<{args.min_papers}")
    if summary["source_questions"] < args.min_questions:
        failures.append(f"source_questions<{args.min_questions}")
    if summary["question_import_coverage"] < args.min_question_import_coverage:
        failures.append(f"question_import_coverage<{args.min_question_import_coverage}")
    if summary["question_knowledge_coverage"] < args.min_question_knowledge_coverage:
        failures.append(f"question_knowledge_coverage<{args.min_question_knowledge_coverage}")
    if summary["specific_knowledge_coverage"] < args.min_specific_knowledge_coverage:
        failures.append(f"specific_knowledge_coverage<{args.min_specific_knowledge_coverage}")
    if wrong_source_questions:
        failures.append("wrong_source_questions>0")

    if failures:
        raise SystemExit("knowledge bank audit failed: " + ", ".join(failures))

    print("knowledge bank audit passed")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit whether P1 paper knowledge points are imported into P3.")
    parser.add_argument(
        "--source",
        type=Path,
        default=ROOT / "campus_p1" / "web_app" / "backend" / "papers",
        help="Directory containing P1 paper.json outputs.",
    )
    parser.add_argument("--knowledge-version", default="2026.1")
    parser.add_argument("--min-papers", type=int, default=50)
    parser.add_argument("--min-questions", type=int, default=1_200)
    parser.add_argument("--min-specific-frequency", type=int, default=3)
    parser.add_argument("--specific-knowledge-limit", type=int, default=3)
    parser.add_argument("--min-question-import-coverage", type=float, default=1.0)
    parser.add_argument("--min-question-knowledge-coverage", type=float, default=1.0)
    parser.add_argument("--min-specific-knowledge-coverage", type=float, default=1.0)
    parser.add_argument("--sample-limit", type=int, default=8)
    parser.add_argument(
        "--ensure-import",
        action="store_true",
        help="Run migrations and import commands before auditing. This writes to the local P3 database.",
    )
    return parser.parse_args()


def load_papers(source: Path) -> list[tuple[Path, dict]]:
    source = source if source.is_absolute() else ROOT / source
    paper_paths = sorted(source.rglob("paper.json"))
    if not paper_paths:
        raise SystemExit(f"No paper.json files found under {source}")
    papers = []
    for path in paper_paths:
        papers.append((path, json.loads(path.read_text(encoding="utf-8"))))
    return papers


def qwen_knowledge_names(question: dict) -> list[str]:
    raw_names = (question.get("qwen_analysis") or {}).get("knowledge_points") or []
    names = []
    for name in raw_names:
        normalized = "".join(str(name or "").split())
        if normalized:
            names.append(normalized[:120])
    return list(dict.fromkeys(names))


def ratio(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 1.0
    return round(numerator / denominator, 6)


def print_samples(label: str, items: list[dict], limit: int) -> None:
    if not items:
        return
    samples = [
        f"{item['paper_name']}#{item['question_no']}:{item['bank_question_id']}"
        for item in items[:limit]
    ]
    print(f"{label}=" + " | ".join(samples))


if __name__ == "__main__":
    main()
