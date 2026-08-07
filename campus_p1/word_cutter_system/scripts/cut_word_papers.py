from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from campus_p2_core.p1_input.normalized_paper import validate_normalized_paper
from campus_p2_core.p1_input.word_cutter import CutSummary, cut_many_docx


def main() -> None:
    parser = argparse.ArgumentParser(description="Cut DOCX math papers into paper.v0.1 JSON.")
    parser.add_argument("input", help="A .docx file, a directory containing .docx files, or a .zip archive.")
    parser.add_argument("--out", default=str(ROOT / "data" / "word_cut_outputs"), help="Output directory.")
    parser.add_argument("--limit", type=int, default=0, help="Only process the first N DOCX files.")
    parser.add_argument("--stage", default="junior_high", choices=["junior_high", "senior_high"])
    parser.add_argument("--grade", default="初三")
    parser.add_argument("--paper-id", default=None, help="Override the paper_id for all inputs.")
    parser.add_argument(
        "--paper-id-from-filename",
        action="store_true",
        help="Use the .docx file stem (without extension) as the paper_id, e.g. "
        "'2025年上海市中考数学试卷.docx' -> '2025年上海市中考数学试卷'.",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    output_dir = Path(args.out)
    with TemporaryDirectory(prefix="word_cutter_") as temp_dir:
        paths = _resolve_input_paths(input_path, Path(temp_dir))
        if args.limit:
            paths = paths[: args.limit]
        if not paths:
            raise SystemExit(f"No .docx files found in {input_path}")

        summaries = cut_many_docx(
            paths,
            output_dir,
            stage=args.stage,
            grade=args.grade,
            paper_id=args.paper_id,
            paper_id_from_filename=args.paper_id_from_filename,
        )
        validation_results = []
        failed = []
        for summary in summaries:
            result = validate_normalized_paper(summary.output_json)
            validation_results.append(result)
            if not result["ok"]:
                failed.append(summary.output_json)

        aggregate = _aggregate(summaries, validation_results)
        print(json.dumps(aggregate, ensure_ascii=False, indent=2))
        if failed:
            raise SystemExit(f"Validation failed for {len(failed)} files.")


def _resolve_input_paths(input_path: Path, temp_dir: Path) -> list[Path]:
    if input_path.is_file() and input_path.suffix.lower() == ".docx":
        return [input_path]
    if input_path.is_dir():
        return sorted(input_path.rglob("*.docx"))
    if input_path.is_file() and input_path.suffix.lower() == ".zip":
        with zipfile.ZipFile(input_path) as archive:
            archive.extractall(temp_dir)
        return sorted(temp_dir.rglob("*.docx"))
    raise SystemExit(f"Unsupported input: {input_path}")


def _aggregate(summaries: list[CutSummary], validation_results: list[dict]) -> dict:
    return {
        "processed_papers": len(summaries),
        "total_questions": sum(item.question_count for item in summaries),
        "total_images": sum(item.image_count for item in summaries),
        "total_formula_marks": sum(item.formula_count for item in summaries),
        "needs_review_questions": sum(item.needs_review_count for item in summaries),
        "validation_ok": all(item["ok"] for item in validation_results),
        "outputs": [
            {
                "paper_id": item.paper_id,
                "questions": item.question_count,
                "images": item.image_count,
                "needs_review": item.needs_review_count,
                "json": item.output_json,
                "warnings": item.warnings,
            }
            for item in summaries
        ],
    }


if __name__ == "__main__":
    main()
