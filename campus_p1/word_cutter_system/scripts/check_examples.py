from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = ROOT / "examples" / "output"


def main() -> None:
    shanghai = _load_paper("2025_000fc7a7")
    hainan = _load_paper("2025_01b4925d")

    q1 = _question(shanghai, "1")
    q5 = _question(shanghai, "5")
    q19_shanghai = _question(shanghai, "19")
    q19_hainan = _question(hainan, "19")

    _assert_contains(q1["options"][0]["text"], "m^{3}", "上海 Q1: 正文上标幂")
    _assert_contains(q1["options"][3]["text"], "$(m^{3})^{3}", "上海 Q1: 括号整体幂")
    _assert_contains(q5["stem_markdown"], r"\overrightarrow{AB}", "上海 Q5: 向量符号")
    _assert_contains(q5["stem_markdown"], r"$|\overrightarrow{AB}+\overrightarrow{BC}|$", "上海 Q5: 向量绝对值")
    _assert_contains(q19_shanghai["stem_markdown"], r"|2-\sqrt{5}|", "上海 Q19: 绝对值")

    _assert_contains(q19_hainan["stem_markdown"], "▲", "海南 Q19: 三角形符号")
    _assert_contains(q19_hainan["stem_markdown"], "★", "海南 Q19: 星形符号")
    _assert_contains(q19_hainan["stem_markdown"], "| 分数段 | 等次 | 人数 |", "海南 Q19: Markdown 表格")
    if q19_hainan["options"]:
        raise AssertionError("海南 Q19 不应把 A、B、C、D、E 等次误切为选择题选项")

    print("example check passed")


def _load_paper(paper_id: str) -> dict:
    path = OUTPUT_ROOT / paper_id / "paper.json"
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _question(paper: dict, question_no: str) -> dict:
    for question in paper["questions"]:
        if question["question_no"] == question_no:
            return question
    raise AssertionError(f"question {question_no} not found in {paper['paper_id']}")


def _assert_contains(value: str, expected: str, message: str) -> None:
    if expected not in value:
        raise AssertionError(f"{message}: missing {expected!r} in {value[:300]!r}")


if __name__ == "__main__":
    main()
