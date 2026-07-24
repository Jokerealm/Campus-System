from __future__ import annotations

import hashlib
import json
import re
import shutil
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable
from xml.etree import ElementTree as ET


NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "m": "http://schemas.openxmlformats.org/officeDocument/2006/math",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "v": "urn:schemas-microsoft-com:vml",
}

REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
IMAGE_PLACEHOLDER_RE = re.compile(r"\[\[image:([^\]]+)\]\]")
OPTION_MARK_RE = re.compile(r"(?<![A-Za-z0-9])([A-D])\s*(?P<sep>[．.、])\s*")
QUESTION_START_RE = re.compile(
    r"^\s*(?:[（(]\s*多选\s*[）)]\s*)?(?:第\s*)?(?P<no>[1-9]\d{0,2})\s*(?P<sep>[．.、])\s*"
    r"(?:[（(]\s*(?P<score>\d+(?:\.\d+)?)\s*分\s*[）)])?"
)

ANSWER_START_MARKERS = (
    "参考答案",
    "试题解析",
    "答案与试题解析",
    "参考答案与试题解析",
    "答案解析",
    "参考答案及解析",
)


@dataclass
class RichText:
    text: str = ""
    markdown: str = ""
    image_refs: list[str] = field(default_factory=list)
    formula_count: int = 0

    def append(self, other: "RichText") -> None:
        self.text += other.text
        self.markdown += other.markdown
        self.image_refs.extend(other.image_refs)
        self.formula_count += other.formula_count


@dataclass
class Block:
    kind: str
    text: str
    markdown: str
    image_refs: list[str]
    formula_count: int


@dataclass
class QuestionDraft:
    no: str
    full_score: float | None
    section: str
    blocks: list[Block] = field(default_factory=list)


@dataclass
class CutSummary:
    source_file: str
    output_json: str
    paper_id: str
    question_count: int
    image_count: int
    formula_count: int
    needs_review_count: int
    warnings: list[str]


class DocxPackage:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._zip = zipfile.ZipFile(path)
        self.relationships = self._load_relationships()
        self._image_bytes_cache: dict[str, bytes] = {}

    def close(self) -> None:
        self._zip.close()

    def read_document_xml(self) -> ET.Element:
        return ET.fromstring(self._zip.read("word/document.xml"))

    def export_image(self, rid: str, output_dir: Path, filename: str) -> str | None:
        target = self.relationships.get(rid)
        if not target:
            return None
        member = _word_target_to_member(target)
        if member not in self._zip.namelist():
            return None

        data = self._image_bytes_cache.get(rid)
        if data is None:
            data = self._zip.read(member)
            self._image_bytes_cache[rid] = data

        suffix = Path(member).suffix.lower() or ".bin"
        output_dir.mkdir(parents=True, exist_ok=True)
        image_path = output_dir / f"{filename}{suffix}"
        image_path.write_bytes(data)
        return image_path.name

    def _load_relationships(self) -> dict[str, str]:
        rels_path = "word/_rels/document.xml.rels"
        if rels_path not in self._zip.namelist():
            return {}
        root = ET.fromstring(self._zip.read(rels_path))
        rels: dict[str, str] = {}
        for rel in root.findall(f"{{{REL_NS}}}Relationship"):
            rid = rel.attrib.get("Id")
            target = rel.attrib.get("Target")
            rel_type = rel.attrib.get("Type", "")
            if rid and target and rel_type.endswith("/image"):
                rels[rid] = target
        return rels


def cut_docx_to_paper(
    docx_path: str | Path,
    output_dir: str | Path,
    *,
    paper_id: str | None = None,
    provider: str = "word_cutter",
    stage: str = "junior_high",
    grade: str = "初三",
) -> tuple[dict[str, Any], CutSummary]:
    source_path = Path(docx_path)
    paper_id = paper_id or _paper_id_from_path(source_path)
    paper_output_dir = Path(output_dir) / paper_id
    if paper_output_dir.exists():
        shutil.rmtree(paper_output_dir)
    assets_dir = paper_output_dir / "assets"
    paper_output_dir.mkdir(parents=True, exist_ok=True)

    docx = DocxPackage(source_path)
    warnings: list[str] = []
    try:
        blocks = _extract_blocks(docx)
        answer_start = _find_answer_start(blocks)
        question_blocks = blocks[:answer_start] if answer_start is not None else blocks
        answer_blocks = blocks[answer_start + 1 :] if answer_start is not None else []

        drafts = _segment_questions(question_blocks, warnings)
        answer_drafts = _segment_questions(answer_blocks, warnings) if answer_blocks else []
        answer_map = _build_answer_map(answer_drafts)

        questions: list[dict[str, Any]] = []
        used_question_nos: set[str] = set()
        for index, draft in enumerate(drafts, start=1):
            normalized = _build_question_payload(
                draft,
                docx,
                assets_dir,
                paper_id,
                index,
                answer_map.get(draft.no, {}),
            )
            if draft.no in used_question_nos:
                normalized["needs_review"] = True
                normalized["parse_confidence"] = min(normalized["parse_confidence"], 0.65)
                warnings.append(f"题号 {draft.no} 重复，请人工复核")
            used_question_nos.add(draft.no)
            questions.append(normalized)

        paper = {
            "schema_version": "paper.v0.1",
            "paper_id": paper_id,
            "source": {
                "name": _paper_name_from_path(source_path),
                "provider": provider,
                "original_file": source_path.name,
            },
            "subject": "math",
            "stage": stage,
            "grade": grade,
            "questions": questions,
        }
        output_json = paper_output_dir / "paper.json"
        output_json.write_text(json.dumps(paper, ensure_ascii=False, indent=2), encoding="utf-8")

        summary = CutSummary(
            source_file=str(source_path),
            output_json=str(output_json),
            paper_id=paper_id,
            question_count=len(questions),
            image_count=sum(len(item["images"]) for item in questions),
            formula_count=sum(_question_formula_count(item) for item in questions),
            needs_review_count=sum(1 for item in questions if item["needs_review"]),
            warnings=warnings,
        )
        return paper, summary
    finally:
        docx.close()


def cut_many_docx(
    input_paths: Iterable[str | Path],
    output_dir: str | Path,
    *,
    provider: str = "word_cutter",
    stage: str = "junior_high",
    grade: str = "初三",
    paper_id: str | None = None,
    paper_id_from_filename: bool = False,
) -> list[CutSummary]:
    summaries: list[CutSummary] = []
    for path in input_paths:
        kwargs: dict[str, Any] = {
            "provider": provider,
            "stage": stage,
            "grade": grade,
        }
        if paper_id is not None:
            kwargs["paper_id"] = paper_id
        elif paper_id_from_filename:
            kwargs["paper_id"] = Path(path).stem
        _, summary = cut_docx_to_paper(path, output_dir, **kwargs)
        summaries.append(summary)

    index_path = Path(output_dir) / "index.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(
        json.dumps([summary.__dict__ for summary in summaries], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summaries


def _extract_blocks(docx: DocxPackage) -> list[Block]:
    root = docx.read_document_xml()
    body = root.find("w:body", NS)
    if body is None:
        return []

    blocks: list[Block] = []
    for child in list(body):
        tag = _local(child.tag)
        if tag == "p":
            rich = _render_element(child)
            block = _rich_to_block("paragraph", rich)
            if block:
                blocks.append(block)
        elif tag == "tbl":
            block = _render_table(child)
            if block:
                blocks.append(block)
    return blocks


def _render_table(table: ET.Element) -> Block | None:
    text_rows: list[list[str]] = []
    markdown_rows: list[list[str]] = []
    image_refs: list[str] = []
    formula_count = 0

    for row in table.findall("w:tr", NS):
        text_cells: list[str] = []
        markdown_cells: list[str] = []
        for cell in row.findall("w:tc", NS):
            parts = [_render_element(child) for child in list(cell) if _local(child.tag) in {"p", "tbl"}]
            text = _clean_inline(" ".join(part.text for part in parts if part.text.strip()))
            markdown = _clean_inline(" ".join(part.markdown for part in parts if part.markdown.strip()))
            if text or markdown:
                text_cells.append(text)
                markdown_cells.append(markdown)
            for part in parts:
                image_refs.extend(part.image_refs)
                formula_count += part.formula_count
        if text_cells or markdown_cells:
            text_rows.append(text_cells)
            markdown_rows.append(markdown_cells or text_cells)

    if not text_rows and not image_refs:
        return None
    return Block(
        kind="table",
        text="\n".join(" | ".join(row) for row in text_rows),
        markdown=_format_markdown_table(markdown_rows or text_rows),
        image_refs=image_refs,
        formula_count=formula_count,
    )


def _format_markdown_table(rows: list[list[str]]) -> str:
    normalized = [[_escape_markdown_table_cell(cell) for cell in row] for row in rows if row]
    if not normalized:
        return ""
    width = max(len(row) for row in normalized)
    padded = [row + [""] * (width - len(row)) for row in normalized]
    if len(padded) == 1:
        return " | ".join(padded[0])

    lines = [
        "| " + " | ".join(padded[0]) + " |",
        "| " + " | ".join("---" for _ in range(width)) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in padded[1:])
    return "\n".join(lines)


def _escape_markdown_table_cell(value: str) -> str:
    return _clean_inline(value).replace("|", r"\|").replace("\n", "<br>")


def _render_element(element: ET.Element) -> RichText:
    tag = _local(element.tag)
    if tag in {"oMath", "oMathPara"}:
        formula = _clean_formula(_convert_omml(element))
        return RichText(text=formula, markdown=f"${formula}$" if formula else "", formula_count=1 if formula else 0)
    if tag == "r" and element.tag.startswith(f"{{{NS['w']}}}"):
        return _render_word_run(element)
    if tag in {"drawing", "pict", "object"}:
        refs = _collect_image_refs(element)
        if not refs:
            return RichText()
        text = "".join(f"[图{idx}]" for idx, _ in enumerate(refs, start=1))
        markdown = "".join(f"[[image:{rid}]]" for rid in refs)
        return RichText(text=text, markdown=markdown, image_refs=refs)
    if tag in {"t", "instrText"}:
        return RichText(text=element.text or "", markdown=element.text or "")
    if tag == "sym":
        symbol = _decode_word_symbol(element)
        return RichText(text=symbol, markdown=symbol)
    if tag == "tab":
        return RichText(text="\t", markdown="\t")
    if tag in {"br", "cr"}:
        return RichText(text="\n", markdown="\n")

    rich = RichText()
    for child in list(element):
        rich.append(_render_element(child))
    return rich


def _decode_word_symbol(element: ET.Element) -> str:
    char = element.attrib.get(f"{{{NS['w']}}}char", "")
    font = element.attrib.get(f"{{{NS['w']}}}font", "")
    if not char:
        return ""

    normalized = char.upper().removeprefix("0X")
    font_key = font.upper()
    symbol_font_map = {
        ("WINGDINGS", "00AB"): "★",
        ("WINGDINGS", "00D8"): "★",
        ("WINGDINGS 2", "00D8"): "★",
        ("WINGDINGS", "00E9"): "▲",
        ("WINGDINGS 3", "0075"): "▲",
        ("SYMBOL", "00B3"): "≥",
        ("SYMBOL", "00A3"): "≤",
        ("SYMBOL", "00B9"): "≠",
        ("SYMBOL", "00B4"): "×",
        ("SYMBOL", "00F7"): "÷",
    }
    mapped = symbol_font_map.get((font_key, normalized))
    if mapped:
        return mapped

    code = int(normalized, 16)
    if code >= 0xF000:
        code -= 0xF000
    try:
        return chr(code)
    except ValueError:
        return ""


def _render_word_run(run: ET.Element) -> RichText:
    rich = RichText()
    for child in list(run):
        if _local(child.tag) == "rPr":
            continue
        rich.append(_render_element(child))

    vert_align = run.find("w:rPr/w:vertAlign", NS)
    align_value = vert_align.attrib.get(f"{{{NS['w']}}}val") if vert_align is not None else ""
    if align_value not in {"superscript", "subscript"}:
        return rich
    if not rich.markdown.strip() or rich.image_refs:
        return rich

    is_superscript = align_value == "superscript"
    script_text = _unicode_script(rich.text, superscript=is_superscript)
    script_markdown = f"^{{{rich.markdown}}}" if is_superscript else f"_{{{rich.markdown}}}"
    return RichText(
        text=script_text,
        markdown=script_markdown,
        image_refs=rich.image_refs,
        formula_count=rich.formula_count + 1,
    )


def _rich_to_block(kind: str, rich: RichText) -> Block | None:
    text = _clean_block(rich.text)
    markdown = _normalize_math_markdown(_clean_block(rich.markdown))
    if not text and not rich.image_refs:
        return None
    return Block(
        kind=kind,
        text=text,
        markdown=markdown or text,
        image_refs=rich.image_refs,
        formula_count=rich.formula_count,
    )


def _collect_image_refs(element: ET.Element) -> list[str]:
    refs: list[str] = []
    for blip in element.findall(".//a:blip", NS):
        rid = blip.attrib.get(f"{{{NS['r']}}}embed") or blip.attrib.get(f"{{{NS['r']}}}link")
        if rid:
            refs.append(rid)
    for image in element.findall(".//v:imagedata", NS):
        rid = image.attrib.get(f"{{{NS['r']}}}id")
        if rid:
            refs.append(rid)
    return refs


def _find_answer_start(blocks: list[Block]) -> int | None:
    for index, block in enumerate(blocks):
        compact = _strip_space(block.text)
        if any(compact.startswith(marker) or (marker in compact and len(compact) <= 40) for marker in ANSWER_START_MARKERS):
            return index
    return None


def _segment_questions(blocks: list[Block], warnings: list[str], *, allow_reset: bool = False) -> list[QuestionDraft]:
    drafts: list[QuestionDraft] = []
    current: QuestionDraft | None = None
    current_section = ""
    last_no = 0

    for block in blocks:
        section = _detect_section(block.text)
        if section:
            current_section = section
            continue

        match = _match_question_start(block.text)
        if match and _is_plausible_question_no(int(match.group("no")), last_no, allow_reset):
            if current is not None:
                drafts.append(current)
            no = match.group("no")
            current = QuestionDraft(
                no=no,
                full_score=_parse_score(match.group("score")),
                section=current_section,
                blocks=[block],
            )
            last_no = int(no)
            continue

        if current is not None:
            current.blocks.append(block)

    if current is not None:
        drafts.append(current)

    if not drafts:
        warnings.append("未识别到题号边界")
    return drafts


def _match_question_start(text: str) -> re.Match[str] | None:
    compact = text.lstrip()
    match = QUESTION_START_RE.match(compact)
    if not match:
        return None

    end = match.end()
    next_char = compact[end : end + 1]
    if match.group("sep") == "." and next_char and next_char.isdigit():
        return None
    return match


def _is_plausible_question_no(no: int, last_no: int, allow_reset: bool) -> bool:
    if last_no == 0:
        return no == 1 or allow_reset
    if no == last_no + 1:
        return True
    if allow_reset and no <= last_no + 1:
        return True
    return False


def _detect_section(text: str) -> str:
    compact = _strip_space(text)
    if "多项选择题" in compact or "多选题" in compact:
        return "multiple_choice"
    if "选择题" in compact:
        return "choice"
    if "填空题" in compact:
        return "blank"
    if "解答题" in compact or "证明题" in compact or "计算题" in compact:
        return "solution"
    return ""


def _build_answer_map(drafts: list[QuestionDraft]) -> dict[str, dict[str, str]]:
    answer_map: dict[str, dict[str, str]] = {}
    for draft in drafts:
        raw = "\n".join(block.markdown or block.text for block in draft.blocks)
        solution = _trim_solution(raw)
        answer = _extract_answer(solution)
        answer_map[draft.no] = {"answer": answer, "solution": solution}
    return answer_map


def _build_question_payload(
    draft: QuestionDraft,
    docx: DocxPackage,
    assets_dir: Path,
    paper_id: str,
    question_index: int,
    answer_info: dict[str, str],
) -> dict[str, Any]:
    raw_text = "\n".join(block.text for block in draft.blocks if block.text or block.image_refs)
    raw_markdown = "\n".join(block.markdown or block.text for block in draft.blocks if block.text or block.image_refs)
    stem_text, stem_markdown, options = _split_stem_and_options(
        raw_text,
        raw_markdown,
        allow_options=_should_split_options(draft.section, raw_text, raw_markdown),
    )
    stem_text = _remove_question_prefix(stem_text)
    stem_markdown = _remove_question_prefix(stem_markdown)

    image_refs = _ordered_unique(ref for block in draft.blocks for ref in block.image_refs)
    exported_images: list[dict[str, str]] = []
    rid_to_markdown: dict[str, str] = {}
    for image_index, rid in enumerate(image_refs, start=1):
        image_id = f"{paper_id}_q{question_index:03d}_img{image_index:02d}"
        filename = docx.export_image(rid, assets_dir, image_id)
        if not filename:
            continue
        rel_path = f"assets/{filename}"
        role = _guess_image_role(raw_markdown, rid, options)
        exported_images.append({"image_id": image_id, "path": rel_path, "role": role})
        rid_to_markdown[rid] = f"![{image_id}]({rel_path})"

    stem_markdown = _replace_image_placeholders(stem_markdown, rid_to_markdown)
    for option in options:
        option["text"] = _replace_image_placeholders(option["text"], rid_to_markdown)

    question_type = _infer_question_type(draft.section, options, stem_text)
    confidence = _estimate_confidence(draft, stem_text, options, exported_images)
    question = {
        "question_id": f"{paper_id}_q{question_index:03d}",
        "question_no": draft.no,
        "question_type": question_type,
        "stem_text": _replace_image_placeholders(stem_text, {}),
        "stem_markdown": stem_markdown,
        "options": options if question_type in {"single_choice", "multiple_choice"} else [],
        "answer": answer_info.get("answer", ""),
        "solution": answer_info.get("solution", ""),
        "full_score": draft.full_score,
        "images": exported_images,
        "knowledge_candidates": [],
        "difficulty": _estimate_difficulty(question_type, stem_text),
        "parse_confidence": confidence,
        "needs_review": confidence < 0.82,
    }
    return question


def _split_stem_and_options(
    raw_text: str,
    raw_markdown: str,
    *,
    allow_options: bool = True,
) -> tuple[str, str, list[dict[str, str]]]:
    if not allow_options:
        return raw_text.strip(), raw_markdown.strip(), []

    markdown_matches = _select_option_matches(list(OPTION_MARK_RE.finditer(raw_markdown)))
    if len(markdown_matches) >= 2:
        stem_markdown = raw_markdown[: markdown_matches[0].start()].strip()
        options: list[dict[str, str]] = []
        for index, match in enumerate(markdown_matches):
            next_start = markdown_matches[index + 1].start() if index + 1 < len(markdown_matches) else len(raw_markdown)
            label = match.group(1)
            text = raw_markdown[match.end() : next_start].strip()
            options.append({"label": label, "text": _clean_option_text(text)})
        text_matches = _select_option_matches(list(OPTION_MARK_RE.finditer(raw_text)))
        stem_text = raw_text[: text_matches[0].start()].strip() if text_matches else stem_markdown
        return stem_text, stem_markdown, _dedupe_options(options)
    return raw_text.strip(), raw_markdown.strip(), []


def _should_split_options(section: str, raw_text: str, raw_markdown: str) -> bool:
    if section in {"choice", "multiple_choice"}:
        return True
    if section in {"blank", "solution"}:
        return False
    if "（　　）" in raw_text or "(　　)" in raw_text:
        return True
    formal_matches = [match for match in OPTION_MARK_RE.finditer(raw_markdown) if match.group("sep") in {"．", "."}]
    return len(_select_option_matches(formal_matches)) >= 2


def _select_option_matches(matches: list[re.Match[str]]) -> list[re.Match[str]]:
    formal = [match for match in matches if match.group("sep") in {"．", "."}]
    selected = formal if len(formal) >= 2 else matches
    for start in range(len(selected)):
        window = selected[start:]
        if not window or window[0].group(1) != "A":
            continue
        expected = ["A", "B", "C", "D"]
        labels = [match.group(1) for match in window[:4]]
        if labels == expected[: len(labels)] and len(labels) >= 2:
            return window
    return []


def _dedupe_options(options: list[dict[str, str]]) -> list[dict[str, str]]:
    deduped: list[dict[str, str]] = []
    seen: set[str] = set()
    for option in options:
        label = option["label"]
        if label in seen:
            continue
        seen.add(label)
        deduped.append(option)
    return deduped[:4]


def _remove_question_prefix(value: str) -> str:
    return QUESTION_START_RE.sub("", value.strip(), count=1).strip()


def _replace_image_placeholders(value: str, mapping: dict[str, str]) -> str:
    def repl(match: re.Match[str]) -> str:
        rid = match.group(1)
        return mapping.get(rid, f"[图片:{rid}]")

    return IMAGE_PLACEHOLDER_RE.sub(repl, value)


def _guess_image_role(raw_markdown: str, rid: str, options: list[dict[str, str]]) -> str:
    placeholder = f"[[image:{rid}]]"
    for option in options:
        if placeholder in option["text"]:
            return f"option_{option['label']}"
    if placeholder in raw_markdown:
        return "stem"
    return "unknown"


def _infer_question_type(section: str, options: list[dict[str, str]], stem: str) -> str:
    if section == "multiple_choice":
        return "multiple_choice"
    if section == "solution":
        return "solution"
    if section == "choice" or len(options) >= 2 or "（　　）" in stem or "(　　)" in stem:
        return "single_choice"
    if section == "blank" or "____" in stem or "填空" in section:
        return "blank"
    return "solution"


def _estimate_confidence(
    draft: QuestionDraft,
    stem_text: str,
    options: list[dict[str, str]],
    exported_images: list[dict[str, str]],
) -> float:
    confidence = 0.96
    q_type = _infer_question_type(draft.section, options, stem_text)
    if len(stem_text) < 8:
        confidence -= 0.18
    if q_type == "single_choice":
        labels = {option["label"] for option in options}
        if labels != {"A", "B", "C", "D"}:
            confidence -= 0.18
        if any(not option["text"] for option in options):
            confidence -= 0.08
    if any(block.image_refs for block in draft.blocks) and not exported_images:
        confidence -= 0.2
    if sum(block.formula_count for block in draft.blocks) > 0:
        confidence -= 0.03
    return round(max(0.45, min(0.99, confidence)), 2)


def _estimate_difficulty(question_type: str, stem: str) -> int:
    length = len(_strip_space(stem))
    if question_type == "solution":
        return 4 if length > 120 else 3
    if length > 140:
        return 4
    if length < 40:
        return 2
    return 3


def _trim_solution(raw: str) -> str:
    text = _clean_block(raw)
    markers = ["【分析】", "【解答】", "【点评】", "故选", "故答案为", "解：", "证明："]
    positions = [text.find(marker) for marker in markers if text.find(marker) >= 0]
    if positions:
        text = text[min(positions) :]
    return text.strip()


def _extract_answer(solution: str) -> str:
    patterns = [
        r"故选[:：]?\s*([A-D])",
        r"答案[:：]\s*([A-D])",
        r"故答案为[:：]\s*([^。\n；;]+)",
        r"答案为[:：]\s*([^。\n；;]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, solution)
        if match:
            return _clean_inline(match.group(1)).strip(" ：:；;。")
    return ""


def _question_formula_count(item: dict[str, Any]) -> int:
    return item.get("stem_markdown", "").count("$") // 2 + item.get("solution", "").count("$") // 2


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _unicode_script(value: str, *, superscript: bool) -> str:
    superscripts = str.maketrans("0123456789+-=()n", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿ")
    subscripts = str.maketrans("0123456789+-=()", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎")
    table = superscripts if superscript else subscripts
    return value.translate(table)


def _normalize_math_markdown(value: str) -> str:
    value = _convert_plain_vector_markers(value)
    value = _wrap_script_atoms(value)
    value = _merge_parenthesized_script_math(value)
    value = _merge_adjacent_math_runs(value)
    value = _wrap_absolute_math(value)
    return value


def _convert_plain_vector_markers(value: str) -> str:
    parts = value.split("$")
    for index in range(0, len(parts), 2):
        parts[index] = re.sub(r"(?<![A-Za-z\\])([A-Za-z]{1,4})(?:→|⃗)", r"$\\overrightarrow{\1}$", parts[index])
    return "$".join(parts)


def _wrap_script_atoms(value: str) -> str:
    parts = value.split("$")
    script_re = re.compile(r"(?<![A-Za-z0-9$\\])(\d*[A-Za-z]+(?:\^\{[^}]+\}|_\{[^}]+\})+)")
    for index in range(0, len(parts), 2):
        parts[index] = script_re.sub(r"$\1$", parts[index])
    return "$".join(parts)


def _merge_parenthesized_script_math(value: str) -> str:
    return re.sub(
        r"[（(]\$([^$]+)\$[）)]((?:\^\{[^}]+\}|_\{[^}]+\})+)",
        r"$(\1)\2$",
        value,
    )


def _merge_adjacent_math_runs(value: str) -> str:
    pattern = re.compile(r"\$([^$]+)\$(\s*[+\-﹣−=＝×÷•:：]\s*)\$([^$]+)\$")
    previous = None
    while previous != value:
        previous = value
        value = pattern.sub(lambda match: f"${match.group(1)}{match.group(2)}{match.group(3)}$", value)
    value = re.sub(r"\$([^$]+)\$\s*\$([^$]+)\$", r"$\1\2$", value)
    return value


def _wrap_absolute_math(value: str) -> str:
    value = re.sub(
        r"\$([^$]*)\$\|([^$|]*)\$([^$]+)\$\|\$([^$]*)\$",
        lambda match: f"${match.group(1)}|{match.group(2)}{match.group(3)}|{match.group(4)}$",
        value,
    )
    value = re.sub(r"(?<!\$)\|\s*\$([^$]+)\$\s*\|(?!\$)", r"$|\1|$", value)
    return value


def _convert_omml(element: ET.Element) -> str:
    tag = _local(element.tag)
    if tag in {"oMath", "oMathPara"}:
        return "".join(_convert_omml(child) for child in list(element))
    if tag in {"r", "mr"}:
        return "".join(_convert_omml(child) for child in list(element))
    if tag == "t":
        return element.text or ""
    if tag == "f":
        num = _convert_named_child(element, "num")
        den = _convert_named_child(element, "den")
        return f"\\frac{{{num}}}{{{den}}}" if num or den else ""
    if tag == "rad":
        deg = _convert_named_child(element, "deg")
        body = _convert_named_child(element, "e")
        return f"\\sqrt[{deg}]{{{body}}}" if deg else f"\\sqrt{{{body}}}"
    if tag == "sSup":
        base = _convert_named_child(element, "e")
        sup = _convert_named_child(element, "sup")
        return f"{_wrap_math_atom(base)}^{{{sup}}}"
    if tag == "sSub":
        base = _convert_named_child(element, "e")
        sub = _convert_named_child(element, "sub")
        return f"{_wrap_math_atom(base)}_{{{sub}}}"
    if tag == "sSubSup":
        base = _convert_named_child(element, "e")
        sub = _convert_named_child(element, "sub")
        sup = _convert_named_child(element, "sup")
        return f"{_wrap_math_atom(base)}_{{{sub}}}^{{{sup}}}"
    if tag == "d":
        begin = _math_prop_value(element, "dPr", "begChr") or "("
        end = _math_prop_value(element, "dPr", "endChr") or ")"
        inner = _convert_named_child(element, "e")
        if begin == "{" and "\\\\" in inner:
            return f"\\begin{{cases}} {inner} \\end{{cases}}"
        return f"{begin}{inner}{end}"
    if tag == "m":
        rows = []
        for row in element.findall("m:mr", NS):
            cells = [_convert_omml(cell) for cell in row.findall("m:e", NS)]
            rows.append(" & ".join(cell for cell in cells if cell))
        return r" \\ ".join(row for row in rows if row)
    if tag == "nary":
        op = _math_prop_value(element, "naryPr", "chr") or "∑"
        sub = _convert_named_child(element, "sub")
        sup = _convert_named_child(element, "sup")
        body = _convert_named_child(element, "e")
        mapped = {"∑": r"\sum", "∫": r"\int", "∏": r"\prod"}.get(op, op)
        limits = ""
        if sub:
            limits += f"_{{{sub}}}"
        if sup:
            limits += f"^{{{sup}}}"
        return f"{mapped}{limits}{body}"
    if tag == "limUpp":
        base = _convert_named_child(element, "e")
        lim = _convert_named_child(element, "lim")
        if lim in {"→", "⃗"}:
            return f"\\overrightarrow{{{base}}}"
        if lim in {"¯", "―", "‾"}:
            return f"\\overline{{{base}}}"
        return f"{base}^{{{lim}}}" if lim else base
    if tag == "limLow":
        base = _convert_named_child(element, "e")
        lim = _convert_named_child(element, "lim")
        return f"{base}_{{{lim}}}" if lim else base
    if tag == "bar":
        body = _convert_named_child(element, "e")
        return f"\\overline{{{body}}}"
    if tag == "acc":
        body = _convert_named_child(element, "e")
        char = _math_prop_value(element, "accPr", "chr")
        if char in {"→", "⃗"}:
            return f"\\overrightarrow{{{body}}}"
        if char:
            return f"\\accentset{{{char}}}{{{body}}}"
        return body
    if tag == "groupChr":
        body = _convert_named_child(element, "e")
        char = _math_prop_value(element, "groupChrPr", "chr")
        return f"\\overbrace{{{body}}}" if char == "⏞" else body
    if tag.endswith("Pr") or tag in {"ctrlPr", "degHide", "jc", "sty", "argPr"}:
        return ""
    return "".join(_convert_omml(child) for child in list(element))


def _convert_named_child(element: ET.Element, child_name: str) -> str:
    child = element.find(f"m:{child_name}", NS)
    if child is None:
        return ""
    return _convert_omml(child)


def _math_prop_value(element: ET.Element, prop_name: str, value_name: str) -> str | None:
    prop = element.find(f"m:{prop_name}/m:{value_name}", NS)
    if prop is None:
        return None
    return prop.attrib.get(f"{{{NS['m']}}}val")


def _wrap_math_atom(value: str) -> str:
    if not value:
        return ""
    if len(value) == 1 or re.fullmatch(r"[A-Za-z0-9]+", value):
        return value
    return f"({value})"


def _clean_formula(value: str) -> str:
    return _clean_inline(value).replace("﹣", "-").replace("＝", "=")


def _clean_option_text(value: str) -> str:
    return _clean_block(value).strip(" \t\r\n|")


def _clean_block(value: str) -> str:
    value = value.replace("\u00a0", " ").replace("\u3000", " ")
    value = re.sub(r"[ \t]{4,}", " ____ ", value)
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def _clean_inline(value: str) -> str:
    value = value.replace("\u00a0", " ").replace("\u3000", " ")
    value = re.sub(r"[ \t]+", " ", value)
    return value.strip()


def _strip_space(value: str) -> str:
    return re.sub(r"\s+", "", value)


def _ordered_unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _parse_score(value: str | None) -> float | None:
    if not value:
        return None
    parsed = float(value)
    return int(parsed) if parsed.is_integer() else parsed


def _paper_id_from_path(path: Path) -> str:
    digest = hashlib.sha1(path.name.encode("utf-8")).hexdigest()[:8]
    ascii_slug = re.sub(r"[^a-zA-Z0-9]+", "_", path.stem).strip("_").lower()
    if not ascii_slug:
        ascii_slug = "paper"
    return f"{ascii_slug}_{digest}"


def _paper_name_from_path(path: Path) -> str:
    return re.sub(r"\.docx?$", "", path.name, flags=re.IGNORECASE)


def _word_target_to_member(target: str) -> str:
    target = target.replace("\\", "/")
    if target.startswith("/"):
        return target.lstrip("/")
    if target.startswith("../"):
        return target[3:]
    return f"word/{target}"
