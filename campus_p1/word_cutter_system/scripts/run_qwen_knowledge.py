"""批量跑 Qwen2.5 知识点评注，写回到 paper.json。

按 design：
- 输入：``examples/output_named/*/paper.json``，或用户自定义 input
- 输出：原位写入新字段 ``qwen_analysis`` 到每道题，原子替换
- 断点续跑：已存在 ``qwen_analysis.status == "ok"`` 或 ``"low_confidence"`` 的题目跳过
- 单卡：默认 ``--device cuda:0``，环境变量 ``QWEN_DEVICE`` 可覆盖
- 跳过 status==ok 和 low_confidence，重试时 status==fallback 的题目重做
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _resolve_paper_paths(input_path: Path) -> list[Path]:
    if input_path.is_file():
        return [input_path]
    if input_path.is_dir():
        return sorted(p for p in input_path.rglob("paper.json"))
    return []


def _atomic_write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(path)


def _skip_decision(qa: object) -> bool:
    """决定是否跳过：成功 / 低置信 跳过，fallback 重跑。"""
    if not isinstance(qa, dict):
        return False
    status = qa.get("status")
    return status in ("ok", "low_confidence")


def _process_paper(
    paper_path: Path,
    extractor,
    force: bool = False,
    max_questions: int = 0,
) -> dict:
    with open(paper_path, "r", encoding="utf-8") as f:
        paper = json.load(f)

    questions = paper.get("questions") or []
    counts = {"total": len(questions), "skipped": 0, "processed": 0, "fallback": 0, "ok": 0}
    t0 = time.time()

    n_to_run = len(questions) if force else 0
    for idx, q in enumerate(questions):
        if not isinstance(q, dict):
            continue
        qa = q.get("qwen_analysis")
        if not force and _skip_decision(qa):
            counts["skipped"] += 1
            continue
        if max_questions and n_to_run >= max_questions:
            counts["skipped"] += 1
            continue

        try:
            result = extractor.extract_for_question(q)
        except Exception as e:
            result = {
                "knowledge_points": [],
                "reasoning": "",
                "confidence": 0.0,
                "status": "error",
                "reason": f"{type(e).__name__}: {e}",
            }

        q["qwen_analysis"] = result
        counts["processed"] += 1
        n_to_run += 1
        if result.get("status") == "ok":
            counts["ok"] += 1
        elif result.get("status") == "fallback" or result.get("status") == "error":
            counts["fallback"] += 1

        # 单题耗时概览，方便看曲线
        if (idx + 1) % 5 == 0 or idx == len(questions) - 1:
            elapsed = time.time() - t0
            rate = counts["processed"] / elapsed if elapsed else 0.0
            print(
                f"  [{paper_path.parent.name}] {idx + 1}/{len(questions)} "
                f"processed={counts['processed']} skipped={counts['skipped']} "
                f"ok={counts['ok']} fallback={counts['fallback']} "
                f"elapsed={elapsed:.1f}s rate={rate:.2f}qps"
            )

    # 回写 paper_meta：方便追溯
    paper_meta = paper.setdefault("meta", {})
    paper_meta["qwen_knowledge_run"] = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "processed": counts["processed"],
        "skipped": counts["skipped"],
        "ok": counts["ok"],
        "fallback": counts["fallback"],
        "model": getattr(extractor.config, "model_path", "?"),
        "device": getattr(extractor.config, "device", "?"),
    }

    _atomic_write_json(paper_path, paper)
    return {
        "paper": paper_path.parent.name,
        "json": str(paper_path),
        **counts,
        "elapsed_sec": round(time.time() - t0, 2),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        default=str(ROOT / "examples" / "output_named"),
        help="paper.json 所在目录，或单个 paper.json 文件",
    )
    parser.add_argument(
        "--device",
        default=os.environ.get("QWEN_DEVICE", "cuda:2"),
        help="运行设备，单卡形如 cuda:0；环境变量 QWEN_DEVICE 可覆盖",
    )
    parser.add_argument(
        "--model-path",
        default=os.environ.get("QWEN_MODEL_PATH", "/home/dataset/yjk_data/Qwen"),
    )
    parser.add_argument("--max-new-tokens", type=int, default=256)
    parser.add_argument("--force", action="store_true", help="覆盖已存在的 qwen_analysis")
    parser.add_argument(
        "--max-questions",
        type=int,
        default=0,
        help="单份 paper 最多跑多少题（0 表示不限制，主要用于测试）",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    papers = _resolve_paper_paths(input_path)
    if not papers:
        raise SystemExit(f"未找到 paper.json：{input_path}")

    from campus_p2_core.p2_stage_5.knowledge_extractor import (
        QwenClient,
        QwenConfig,
    )

    cfg = QwenConfig(
        model_path=args.model_path,
        device=args.device,
        max_new_tokens=args.max_new_tokens,
    )

    print(f"[init] device={cfg.device} model={cfg.model_path}")
    extractor = QwenClient.get(cfg)
    print(f"[init] model loaded to {extractor.model.device}")

    overall = []
    for paper_path in papers:
        print(f"\n--- {paper_path.parent.name} ---")
        summary = _process_paper(
            paper_path,
            extractor,
            force=args.force,
            max_questions=args.max_questions,
        )
        overall.append(summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))

    print("\n========== 汇总 ==========")
    print(json.dumps({"papers": overall}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
