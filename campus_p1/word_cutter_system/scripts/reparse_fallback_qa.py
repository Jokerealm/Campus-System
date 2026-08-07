"""回填：对 paper.json 中 ``status == "fallback"`` 的题目，
用本地解析器重跑 ``raw_output``，恢复成 ok / low_confidence。

不重新调用 GPU，纯本地处理。脚本会原地写回 paper.json（原子替换），
并打印每道题修复前/后的差异。
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _atomic_write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        default=str(ROOT / "examples" / "output_named"),
        help="paper.json 所在目录，或单个 paper.json 文件",
    )
    args = parser.parse_args()

    # 强制 reload，确保拿到的解析器是磁盘最新版
    import campus_p2_core.p2_stage_5.knowledge_extractor as kex
    importlib.reload(kex)

    input_path = Path(args.input)
    if input_path.is_file():
        papers = [input_path]
    elif input_path.is_dir():
        papers = sorted(p for p in input_path.rglob("paper.json"))
    else:
        raise SystemExit(f"无效输入：{input_path}")

    total_fixed = 0
    total_examined = 0
    for paper_path in papers:
        with open(paper_path, "r", encoding="utf-8") as f:
            paper = json.load(f)

        changed = False
        for q in paper.get("questions") or []:
            qa = q.get("qwen_analysis") or {}
            if qa.get("status") != "fallback":
                continue
            total_examined += 1
            raw = qa.get("raw_output") or ""
            if not raw:
                continue
            obj = kex._parse_json_object(raw)
            if obj is None or not kex._validate_extraction(obj):
                continue
            n = kex._normalize_extraction(obj, source_step=qa.get("parse_step", 0))
            print(f"  [FIXED] {paper_path.parent.name} :: "
                  f"{q.get('question_id')} :: kp={n['knowledge_points']} "
                  f"conf={n['confidence']}")
            q["qwen_analysis"] = {
                **n,
                "raw_outputs": qa.get("raw_outputs") or [{"step": 0, "raw": raw}],
                "recovered_by": "post_run_reparse_v1",
            }
            total_fixed += 1
            changed = True

        if changed:
            _atomic_write_json(paper_path, paper)

    print(f"\n=== 回填完成：检查 {total_examined} 道 fallback 题，修复 {total_fixed} 道 ===")


if __name__ == "__main__":
    main()
