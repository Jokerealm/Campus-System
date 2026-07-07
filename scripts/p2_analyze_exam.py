from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from campus_p2_core.p2_teacher.service import P2TeacherService


def main() -> None:
    parser = argparse.ArgumentParser(description="Run campus-system-p2 teacher-side exam analysis.")
    parser.add_argument("--paper", default=str(ROOT / "examples" / "normalized_paper_demo.json"))
    parser.add_argument("--scores", default=str(ROOT / "examples" / "sample_exam_scores.xlsx"))
    parser.add_argument("--exam-id", default="exam_demo_001")
    parser.add_argument("--class-name", default="高二3班")
    parser.add_argument("--out", default=str(ROOT / "data" / "exams" / "p2_exam_analysis_demo.json"))
    parser.add_argument("--report-md", default=None)
    parser.add_argument("--report-docx", default=None)
    parser.add_argument("--no-report-files", action="store_true")
    args = parser.parse_args()

    service = P2TeacherService()
    result = service.run_analysis(
        paper_json_path=args.paper,
        score_file_path=args.scores,
        exam_id=args.exam_id,
        class_name=args.class_name,
        output_dir=Path(args.out).parent,
        json_output_path=args.out,
        markdown_output_path=args.report_md,
        docx_output_path=args.report_docx,
        export_report_files=not args.no_report_files,
    )

    analysis = result.analysis
    print(f"Wrote JSON: {result.json_path}")
    if result.markdown_path:
        print(f"Wrote Markdown: {result.markdown_path}")
    if result.docx_path:
        print(f"Wrote DOCX: {result.docx_path}")
    print(f"questions={len(analysis.question_analysis)}")
    print(f"weak_points={len(analysis.knowledge_diagnostics)}")
    print(f"p3_requests={len(analysis.p3_search_requests)}")
    if analysis.warnings:
        print("warnings:")
        for warning in analysis.warnings:
            print(f"- {warning}")


if __name__ == "__main__":
    main()
