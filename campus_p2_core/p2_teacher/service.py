from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from campus_p2_core.contracts.p2 import P2ExamAnalysis
from campus_p2_core.p2_teacher.analyzer import analyze_exam
from campus_p2_core.p2_teacher.report_exporter import export_analysis_docx, export_analysis_markdown


@dataclass(slots=True)
class P2RunResult:
    analysis: P2ExamAnalysis
    json_path: Path
    markdown_path: Path | None = None
    docx_path: Path | None = None

    @property
    def output_paths(self) -> list[Path]:
        return [path for path in [self.json_path, self.markdown_path, self.docx_path] if path is not None]


class P2TeacherService:
    """Service boundary used by CLI, GUI, and future API adapters."""

    def run_analysis(
        self,
        paper_json_path: str | Path,
        score_file_path: str | Path,
        exam_id: str = "exam_demo_001",
        class_name: str = "高二3班",
        output_dir: str | Path = "data/exams",
        json_output_path: str | Path | None = None,
        markdown_output_path: str | Path | None = None,
        docx_output_path: str | Path | None = None,
        export_report_files: bool = True,
    ) -> P2RunResult:
        analysis = analyze_exam(
            paper_json_path=paper_json_path,
            score_file_path=score_file_path,
            exam_id=exam_id,
            class_name=class_name,
        )

        base_dir = Path(output_dir)
        base_dir.mkdir(parents=True, exist_ok=True)
        stem = _safe_stem(exam_id or analysis.paper_id)

        json_path = Path(json_output_path) if json_output_path else base_dir / f"{stem}_analysis.json"
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(analysis.model_dump_json(indent=2), encoding="utf-8")

        markdown_path: Path | None = None
        docx_path: Path | None = None
        if export_report_files:
            markdown_path = export_analysis_markdown(
                analysis,
                Path(markdown_output_path) if markdown_output_path else base_dir / f"{stem}_report.md",
            )
            docx_path = export_analysis_docx(
                analysis,
                Path(docx_output_path) if docx_output_path else base_dir / f"{stem}_report.docx",
            )

        return P2RunResult(
            analysis=analysis,
            json_path=json_path,
            markdown_path=markdown_path,
            docx_path=docx_path,
        )


def _safe_stem(value: str) -> str:
    stem = re.sub(r"[^0-9A-Za-z._-]+", "_", value.strip()).strip("._-")
    return stem or "p2_exam_analysis"
