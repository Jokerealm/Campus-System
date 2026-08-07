from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT))

from campus_p2_core.p1_input.word_cutter import CutSummary, cut_docx_to_paper
from campus_p2_core.p1_input.normalized_paper import validate_normalized_paper


# 用户指定的处理顺序（与对话里给的顺序一致）
FILES_IN_ORDER = [
    "2025年上海市中考数学试卷.docx",
    "2025年福建省中考数学试卷.docx",
    "2025年海南省中考数学试卷.docx",
]

INPUT_DIR = ROOT / "examples" / "input"
OUTPUT_DIR = ROOT / "examples" / "output_named"


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    summaries: list[CutSummary] = []
    results: list[dict] = []

    for filename in FILES_IN_ORDER:
        docx_path = INPUT_DIR / filename
        if not docx_path.exists():
            raise SystemExit(f"Missing input: {docx_path}")

        # paper_id 直接用文件名 stem，保持与 word 试卷一致
        paper_id = docx_path.stem
        print(f"==> Processing {filename} -> paper_id={paper_id}")

        _, summary = cut_docx_to_paper(
            docx_path,
            OUTPUT_DIR,
            paper_id=paper_id,
        )
        result = validate_normalized_paper(summary.output_json)
        summaries.append(summary)
        results.append(result)

        print(json.dumps({
            "paper_id": summary.paper_id,
            "questions": summary.question_count,
            "images": summary.image_count,
            "formula_marks": summary.formula_count,
            "needs_review": summary.needs_review_count,
            "validation_ok": result["ok"],
            "output_dir": str(Path(summary.output_json).parent),
            "warnings": summary.warnings,
        }, ensure_ascii=False, indent=2))

    aggregate = {
        "processed_papers": len(summaries),
        "total_questions": sum(s.question_count for s in summaries),
        "total_images": sum(s.image_count for s in summaries),
        "total_formula_marks": sum(s.formula_count for s in summaries),
        "needs_review_questions": sum(s.needs_review_count for s in summaries),
        "validation_ok": all(r["ok"] for r in results),
    }
    print("\n=== Aggregate ===")
    print(json.dumps(aggregate, ensure_ascii=False, indent=2))

    failed = [r for r in results if not r["ok"]]
    if failed:
        raise SystemExit(f"Validation failed for {len(failed)} files.")


if __name__ == "__main__":
    main()
