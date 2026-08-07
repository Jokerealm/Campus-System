"""端到端流水线：docx → 切题 → Qwen 知识点评注 → 原子写回 paper.json。

用法：

    python scripts/pipeline.py --input examples/input \\
        --out examples/output_named \\
        --device cuda:2

输入可以是单个 .docx 文件、含 .docx 的目录、或 .zip 包。
每份 docx 走两步：
    1) cut_word_papers 内部的 cut_docx_to_paper → paper.json 写盘
    2) 重新读回内存 → Qwen2.5-3B 逐题 extract_for_question → 原子替换

输出 paper.json 顶层新增 ``meta.pipeline_run`` 字段，记录本次运行元信息。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _resolve_input_paths(input_path: Path, temp_dir: Path) -> list[Path]:
    if input_path.is_file() and input_path.suffix.lower() == ".docx":
        return [input_path]
    if input_path.is_dir():
        return sorted(input_path.rglob("*.docx"))
    if input_path.is_file() and input_path.suffix.lower() == ".zip":
        with zipfile.ZipFile(input_path) as archive:
            archive.extractall(temp_dir)
        return sorted(temp_dir.rglob("*.docx"))
    raise SystemExit(f"不支持的输入: {input_path}")


def _atomic_write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(path)


def _skip_decision(qa: object) -> bool:
    if not isinstance(qa, dict):
        return False
    return qa.get("status") in ("ok", "low_confidence")


def _process_one_paper(
    docx_path: Path,
    output_dir: Path,
    extractor,
    reparser,
    stage: str,
    grade: str,
) -> dict:
    """单份 docx：切题 → 写盘 → 读回 → 知识点评注 → 回写。"""
    from campus_p2_core.p1_input.word_cutter import cut_docx_to_paper
    from campus_p2_core.p1_input.normalized_paper import validate_normalized_paper

    paper_id = docx_path.stem
    paper_output_dir = output_dir / paper_id

    t_cut = time.time()
    paper, summary = cut_docx_to_paper(
        docx_path,
        output_dir,
        provider="word_cutter",
        stage=stage,
        grade=grade,
        paper_id=paper_id,
    )
    cut_elapsed = time.time() - t_cut

    validation = validate_normalized_paper(summary.output_json)
    if not validation.get("ok"):
        return {
            "paper": paper_id,
            "docx": str(docx_path),
            "json": summary.output_json,
            "stage": "cut",
            "validation": validation,
            "questions": 0,
            "ok": 0,
            "fallback": 0,
            "elapsed_sec": round(cut_elapsed, 2),
            "error": "cut_validation_failed",
        }

    counts = {"total": len(paper.get("questions") or []), "skipped": 0, "processed": 0, "ok": 0, "fallback": 0}
    t_q = time.time()

    for idx, q in enumerate(paper.get("questions") or []):
        qa = q.get("qwen_analysis")
        if _skip_decision(qa):
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
        if result.get("status") == "ok":
            counts["ok"] += 1
        elif result.get("status") in ("fallback", "error"):
            counts["fallback"] += 1
            # 即时二次解析：模型原始输出若仍可挽救，落盘前先吃一遍新解析器
            raw = result.get("raw_output") or ""
            if raw and result.get("status") == "fallback":
                obj = reparser._parse_json_object(raw)
                if obj is not None and reparser._validate_extraction(obj):
                    n = reparser._normalize_extraction(obj, source_step=0)
                    n["raw_outputs"] = result.get("raw_outputs") or [{"step": 0, "raw": raw}]
                    n["recovered_by"] = "pipeline_inline_reparse_v1"
                    q["qwen_analysis"] = n
                    counts["ok"] += 1
                    counts["fallback"] -= 1

        if (idx + 1) % 5 == 0 or idx == len(paper.get("questions") or []) - 1:
            elapsed = time.time() - t_q
            rate = counts["processed"] / elapsed if elapsed else 0.0
            print(
                f"  [{paper_id}] {idx + 1}/{counts['total']} "
                f"processed={counts['processed']} skipped={counts['skipped']} "
                f"ok={counts['ok']} fallback={counts['fallback']} "
                f"elapsed={elapsed:.1f}s rate={rate:.2f}qps"
            )

    paper.setdefault("meta", {})["pipeline_run"] = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "device": getattr(extractor.config, "device", "?"),
        "model": getattr(extractor.config, "model_path", "?"),
        "stage": stage,
        "grade": grade,
        "cut_elapsed_sec": round(cut_elapsed, 2),
        "qwen_elapsed_sec": round(time.time() - t_q, 2),
        **counts,
    }

    _atomic_write_json(Path(summary.output_json), paper)

    return {
        "paper": paper_id,
        "docx": str(docx_path),
        "json": summary.output_json,
        "stage": "ok",
        **counts,
        "cut_elapsed_sec": round(cut_elapsed, 2),
        "qwen_elapsed_sec": round(time.time() - t_q, 2),
        "total_elapsed_sec": round(time.time() - t_cut, 2),
        "validation_ok": validation.get("ok"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="docx 目录 / 单 docx / zip")
    parser.add_argument("--out", required=True, help="输出根目录（每份 docx 一子目录）")
    parser.add_argument("--device", default=os.environ.get("QWEN_DEVICE", "cuda:2"))
    parser.add_argument(
        "--model-path",
        default=os.environ.get("QWEN_MODEL_PATH", "/home/dataset/yjk_data/Qwen"),
    )
    parser.add_argument("--max-new-tokens", type=int, default=256)
    parser.add_argument("--stage", default="junior_high", choices=["junior_high", "senior_high"])
    parser.add_argument("--grade", default="初三")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    input_path = Path(args.input)
    output_dir = Path(args.out)
    output_dir.mkdir(parents=True, exist_ok=True)

    with TemporaryDirectory(prefix="pipeline_") as temp:
        paths = _resolve_input_paths(input_path, Path(temp))
        if args.limit:
            paths = paths[: args.limit]
        if not paths:
            raise SystemExit(f"未找到 docx: {input_path}")
        print(f"[plan] 共 {len(paths)} 份 docx 待处理")

        from campus_p2_core.p2_stage_5 import knowledge_extractor as kex
        from campus_p2_core.p2_stage_5 import knowledge_extractor as reparser_mod
        import importlib
        importlib.reload(kex)

        cfg = kex.QwenConfig(
            model_path=args.model_path,
            device=args.device,
            max_new_tokens=args.max_new_tokens,
        )
        print(f"[init] device={cfg.device} model={cfg.model_path}")
        extractor = kex.QwenClient.get(cfg)
        print(f"[init] model loaded to {extractor.model.device}")

        overall = []
        for docx in paths:
            print(f"\n=== {docx.name} ===")
            result = _process_one_paper(
                docx, output_dir, extractor, reparser_mod,
                stage=args.stage, grade=args.grade,
            )
            overall.append(result)
            print(json.dumps(result, ensure_ascii=False, indent=2))

    print("\n========== 端到端汇总 ==========")
    print(json.dumps({"papers": overall, "total": len(overall)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
