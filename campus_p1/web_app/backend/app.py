"""Flask app for AI 切题识别 demo.

端到端：上传 docx -> 调用现有 pipeline (cut + Qwen 知识点) -> 进度 SSE ->
前端可编辑展示。

启动：
    python web_app/backend/app.py

依赖：flask
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import shutil
import sys
import threading
import time
import traceback
import uuid
from pathlib import Path
from flask import (
    Flask,
    Response,
    abort,
    jsonify,
    request,
    send_file,
    send_from_directory,
    stream_with_context,
)

ROOT = Path(__file__).resolve().parents[2]
WORD_CUTTER_ROOT = ROOT / "word_cutter_system"
sys.path.insert(0, str(WORD_CUTTER_ROOT))

PAPERS_DIR = Path(__file__).resolve().parent / "papers"
PAPERS_DIR.mkdir(parents=True, exist_ok=True)

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

# 本服务器固定使用第 2 张 GPU；前端右上角展示与后台识别都遵循此默认值
DEFAULT_DEVICE = "cuda:2"

# ------------------------------------------------------------------- pipeline
# 关键：后台线程复用 Qwen 单例，避免每次识别都重载 6GB 模型
_qwen_lock = threading.Lock()
_qwen_client = None
_qwen_reparser = None


def _get_qwen(device: str):
    global _qwen_client, _qwen_reparser
    with _qwen_lock:
        if _qwen_client is None:
            import importlib

            from campus_p2_core.p2_stage_5 import knowledge_extractor as kex

            importlib.reload(kex)
            cfg = kex.QwenConfig(device=device)
            print(f"[qwen] loading model on {cfg.device}...", flush=True)
            _qwen_client = kex.QwenClient.get(cfg)
            _qwen_reparser = kex
            print(f"[qwen] model loaded to {_qwen_client.model.device}", flush=True)
        return _qwen_client, _qwen_reparser


def _run_task(task_id: str, docx_paths: list[Path], stage: str, grade: str, device: str, q: "queue.Queue[dict]"):
    """单次识别任务。在后台线程里跑，逐题推进度到 SSE 队列。"""
    try:
        from campus_p2_core.p1_input.word_cutter import cut_docx_to_paper

        extractor, reparser_mod = _get_qwen(device)

        for paper_idx, docx_path in enumerate(docx_paths):
            paper_id = docx_path.stem
            paper_output_dir = PAPERS_DIR / paper_id
            paper_output_dir.mkdir(parents=True, exist_ok=True)

            q.put({"event": "paper_start", "paperIndex": paper_idx, "paperName": paper_id})

            try:
                paper, summary = cut_docx_to_paper(
                    docx_path,
                    PAPERS_DIR,
                    provider="word_cutter",
                    stage=stage,
                    grade=grade,
                    paper_id=paper_id,
                )
            except Exception as e:
                q.put({
                    "event": "paper_error",
                    "paperIndex": paper_idx,
                    "paperName": paper_id,
                    "error": f"{type(e).__name__}: {e}",
                    "trace": traceback.format_exc(),
                })
                continue

            questions = paper.get("questions") or []
            total = len(questions)
            ok_count = 0
            fallback_count = 0
            for q_idx, question in enumerate(questions):
                try:
                    result = extractor.extract_for_question(question)
                except Exception as e:
                    result = {
                        "knowledge_points": [],
                        "reasoning": "",
                        "confidence": 0.0,
                        "status": "error",
                        "reason": f"{type(e).__name__}: {e}",
                    }

                # inline reparse: fallback 时尝试本地解析
                if result.get("status") == "fallback":
                    raw = result.get("raw_output") or ""
                    if raw:
                        obj = reparser_mod._parse_json_object(raw)
                        if obj is not None and reparser_mod._validate_extraction(obj):
                            n = reparser_mod._normalize_extraction(obj, source_step=0)
                            n["raw_outputs"] = result.get("raw_outputs") or [{"step": 0, "raw": raw}]
                            n["recovered_by"] = "app_inline_reparse_v1"
                            result = n

                question["qwen_analysis"] = result
                if result.get("status") == "ok":
                    ok_count += 1
                elif result.get("status") in ("fallback", "error"):
                    fallback_count += 1

                q.put({
                    "event": "progress",
                    "paperIndex": paper_idx,
                    "paperName": paper_id,
                    "questionIndex": q_idx,
                    "questionTotal": total,
                    "status": result.get("status", "?"),
                    "confidence": result.get("confidence", 0.0),
                })

            paper.setdefault("meta", {})["pipeline_run"] = {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "device": getattr(extractor.config, "device", "?"),
                "model": getattr(extractor.config, "model_path", "?"),
                "stage": stage,
                "grade": grade,
                "total": total,
                "ok": ok_count,
                "fallback": fallback_count,
            }

            paper_json_path = paper_output_dir / "paper.json"
            with open(paper_json_path, "w", encoding="utf-8") as f:
                json.dump(paper, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())

            q.put({
                "event": "paper_done",
                "paperIndex": paper_idx,
                "paperName": paper_id,
                "total": total,
                "ok": ok_count,
                "fallback": fallback_count,
            })

        q.put({"event": "finished", "taskId": task_id})

    except Exception as e:
        q.put({
            "event": "fatal",
            "error": f"{type(e).__name__}: {e}",
            "trace": traceback.format_exc(),
        })


# ----------------------------------------------------------------- task state
TASKS: dict[str, dict[str, Any]] = {}


def _create_task(docx_paths: list[Path], stage: str, grade: str, device: str) -> str:
    task_id = uuid.uuid4().hex[:12]
    q: "queue.Queue[dict]" = queue.Queue()
    TASKS[task_id] = {
        "queue": q,
        "docx_paths": docx_paths,
        "stage": stage,
        "grade": grade,
        "device": device,
        "thread": None,
        "created_at": time.time(),
    }
    t = threading.Thread(
        target=_run_task,
        args=(task_id, docx_paths, stage, grade, device, q),
        daemon=True,
    )
    TASKS[task_id]["thread"] = t
    t.start()
    return task_id


# ----------------------------------------------------------------------- app
app = Flask(__name__, static_folder=None)


# --------- 静态资源 / 入口页 ---------
@app.route("/")
def index():
    return send_from_directory(FRONTEND_DIR, "index.html")


@app.route("/static/<path:filename>")
def static_files(filename: str):
    return send_from_directory(FRONTEND_DIR / "static", filename)


# --------- 试卷图片代理（避免前端跨域读 file://） ---------
@app.route("/api/papers/<paper_id>/assets/<path:filename>")
def paper_asset(paper_id: str, filename: str):
    asset_dir = PAPERS_DIR / paper_id / "assets"
    if not asset_dir.exists():
        abort(404)
    return send_from_directory(asset_dir, filename)


# --------- 上传 ---------
@app.route("/api/upload", methods=["POST"])
def upload():
    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "no files"}), 400
    upload_dir = PAPERS_DIR / "_uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    saved: list[dict[str, str]] = []
    for f in files:
        name = f.filename or "unnamed.docx"
        if not name.lower().endswith(".docx"):
            continue
        # 处理中文文件名
        safe_name = name
        target = upload_dir / safe_name
        f.save(target)
        saved.append({"name": safe_name, "path": str(target), "size": target.stat().st_size})
    return jsonify({"files": saved})


# --------- 启动识别 ---------
@app.route("/api/tasks/start", methods=["POST"])
def start_task():
    body = request.get_json(silent=True) or {}
    docx_paths_str: list[str] = body.get("docxPaths") or []
    stage = body.get("stage", "junior_high")
    grade = body.get("grade", "初三")
    device = body.get("device", os.environ.get("QWEN_DEVICE", DEFAULT_DEVICE))
    if not docx_paths_str:
        return jsonify({"error": "docxPaths empty"}), 400
    docx_paths = [Path(p) for p in docx_paths_str]
    for p in docx_paths:
        if not p.exists():
            return jsonify({"error": f"file not found: {p}"}), 400
    task_id = _create_task(docx_paths, stage, grade, device)
    return jsonify({"taskId": task_id})


# --------- SSE 进度流 ---------
@app.route("/api/tasks/<task_id>/stream")
def task_stream(task_id: str):
    task = TASKS.get(task_id)
    if not task:
        return jsonify({"error": "task not found"}), 404
    q: "queue.Queue[dict]" = task["queue"]

    @stream_with_context
    def generate():
        # 发送初始心跳
        yield f"data: {json.dumps({'event': 'connected', 'taskId': taskId_safe(task_id)}, ensure_ascii=False)}\n\n"
        while True:
            try:
                msg = q.get(timeout=30)
            except queue.Empty:
                # 心跳
                yield ": ping\n\n"
                continue
            yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"
            if msg.get("event") in ("finished", "fatal"):
                break

    return Response(generate(), mimetype="text/event-stream")


def taskId_safe(task_id: str) -> str:
    return task_id


# --------- 试卷列表 ---------
@app.route("/api/papers", methods=["GET"])
def list_papers():
    papers = []
    if PAPERS_DIR.exists():
        for d in sorted(PAPERS_DIR.iterdir()):
            if not d.is_dir() or d.name.startswith("_"):
                continue
            paper_json = d / "paper.json"
            if not paper_json.exists():
                continue
            try:
                with open(paper_json, "r", encoding="utf-8") as f:
                    paper = json.load(f)
            except Exception:
                continue
            questions = paper.get("questions") or []
            pipeline_run = (paper.get("meta") or {}).get("pipeline_run") or {}
            papers.append({
                "paperId": d.name,
                "sourceName": (paper.get("source") or {}).get("name", d.name),
                "questionCount": len(questions),
                "ok": pipeline_run.get("ok", 0),
                "fallback": pipeline_run.get("fallback", 0),
                "stage": paper.get("stage"),
                "grade": paper.get("grade"),
                "mtime": paper_json.stat().st_mtime,
            })
    return jsonify({"papers": papers})


# --------- 单份试卷详情 ---------
@app.route("/api/papers/<paper_id>", methods=["GET"])
def get_paper(paper_id: str):
    paper_json = PAPERS_DIR / paper_id / "paper.json"
    if not paper_json.exists():
        return jsonify({"error": "not found"}), 404
    with open(paper_json, "r", encoding="utf-8") as f:
        paper = json.load(f)
    return jsonify(paper)


# --------- 单题编辑保存 ---------
@app.route("/api/papers/<paper_id>/questions/<qid>", methods=["PUT"])
def update_question(paper_id: str, qid: str):
    paper_json = PAPERS_DIR / paper_id / "paper.json"
    if not paper_json.exists():
        return jsonify({"error": "not found"}), 404
    with open(paper_json, "r", encoding="utf-8") as f:
        paper = json.load(f)

    patch = request.get_json(silent=True) or {}
    found = False
    for q in paper.get("questions") or []:
        if q.get("question_id") == qid:
            # 可编辑字段白名单
            if "stem_text" in patch:
                q["stem_text"] = patch["stem_text"]
            if "stem_markdown" in patch:
                q["stem_markdown"] = patch["stem_markdown"]
            if "options" in patch:
                q["options"] = patch["options"]
            if "answer" in patch:
                q["answer"] = patch["answer"]
            if "solution" in patch:
                q["solution"] = patch["solution"]
            if "knowledge_points" in patch or "reasoning" in patch or "confidence" in patch:
                qa = q.setdefault("qwen_analysis", {})
                if "knowledge_points" in patch:
                    qa["knowledge_points"] = patch["knowledge_points"]
                if "reasoning" in patch:
                    qa["reasoning"] = patch["reasoning"]
                if "confidence" in patch:
                    qa["confidence"] = float(patch["confidence"])
                qa["status"] = "ok"  # 用户编辑后强制视为 ok
                qa["edited_by_user"] = True
            found = True
            break

    if not found:
        return jsonify({"error": "question not found"}), 404

    paper["meta"].setdefault("edits", []).append({
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "qid": qid,
        "fields": list(patch.keys()),
    })

    tmp = paper_json.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(paper, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(paper_json)
    return jsonify({"ok": True})


# --------- 删除 ---------
@app.route("/api/papers/<paper_id>", methods=["DELETE"])
def delete_paper(paper_id: str):
    target = PAPERS_DIR / paper_id
    if target.exists() and target.is_dir():
        shutil.rmtree(target)
    return jsonify({"ok": True})


# --------- 服务状态 ---------
@app.route("/api/health")
def health():
    """本服务器锁定 GPU 2。cuda_available 只表示 torch 运行时能否真的初始化，
    但设备选择始终是 DEFAULT_DEVICE。"""
    info = {
        "cuda_available": False,
        "device": DEFAULT_DEVICE,
        "default_device": DEFAULT_DEVICE,
        "requested_device": DEFAULT_DEVICE,
    }
    try:
        import torch

        info["cuda_available"] = bool(torch.cuda.is_available())
        if info["cuda_available"]:
            info["device_count"] = torch.cuda.device_count()
    except Exception as e:
        info["torch_error"] = str(e)
    return jsonify(info)


# ===================================================================
# 教学反馈报告模块
# ===================================================================
import io as _io
import re as _re
from pathlib import Path as _Path
from werkzeug.utils import secure_filename as _secure_filename

from feedback import report_builder as _fb_builder, schema as _fb_schema
from feedback.template_render import markdown_to_html as _md2html, html_to_pdf as _html2pdf

_FEEDBACK_DIR = _Path(__file__).parent / "feedback"
_TEMPLATE_DIR = _FEEDBACK_DIR / "templates"
_USER_TEMPLATE_DIR = PAPERS_DIR / "_feedback_templates"
_USER_TEMPLATE_DIR.mkdir(exist_ok=True)
_DEFAULT_MD = str(_TEMPLATE_DIR / "default.md")
# 兼容历史内置文件名 default.md.j2（早期版本扩展名）
_DEFAULT_MD_ALIAS = "default.md.j2"
_DEFAULT_MD_NAME = "default.md"
_DEFAULT_DOCX = str(_TEMPLATE_DIR / "default.docx")
_DEFAULT_MD_NAME = "default.md"
_DEFAULT_DOCX_NAME = "default.docx"


def _list_templates() -> list[dict]:
    items = []
    if _Path(_DEFAULT_MD).exists():
        items.append({"name": _DEFAULT_MD_NAME, "format": "md", "builtin": True, "url": f"/api/feedback/templates/{_DEFAULT_MD_NAME}"})
    if _Path(_DEFAULT_DOCX).exists():
        items.append({"name": _DEFAULT_DOCX_NAME, "format": "docx", "builtin": True, "url": f"/api/feedback/templates/{_DEFAULT_DOCX_NAME}"})
    for f in sorted(_USER_TEMPLATE_DIR.iterdir()):
        if f.suffix.lower() in (".md", ".j2", ".docx", ".txt"):
            items.append({"name": f.name, "format": _fmt_of(f), "builtin": False, "url": f"/api/feedback/templates/{f.name}"})
    return items


def _fmt_of(p: _Path) -> str:
    s = p.suffix.lower()
    if s in (".md", ".j2", ".txt"):
        return "md"
    if s == ".docx":
        return "docx"
    return "other"


def _resolve_template(name: str) -> str | None:
    """优先用户上传，回落到默认。

    兼容历史：若上传时使用了 default.md.j2，也能在内置里找到。
    """
    p1 = _USER_TEMPLATE_DIR / name
    if p1.exists():
        return str(p1)
    p2 = _TEMPLATE_DIR / name
    if p2.exists():
        return str(p2)
    if name == _DEFAULT_MD_ALIAS:
        # 历史前端缓存的可能叫 default.md.j2
        if _Path(_DEFAULT_MD).exists():
            return _DEFAULT_MD
    return None


@app.route("/api/feedback/templates", methods=["GET"])
def feedback_list_templates():
    return jsonify({"templates": _list_templates()})


@app.route("/api/feedback/templates/<name>", methods=["GET"])
def feedback_get_template(name: str):
    """下载模板文件（默认 / 用户上传）。"""
    name = _secure_filename(name)
    path = _resolve_template(name)
    if not path:
        return jsonify({"error": f"未找到模板：{name}"}), 404
    return send_file(path, as_attachment=True, download_name=name)


@app.route("/api/feedback/templates", methods=["POST"])
def feedback_upload_template():
    """教师上传新模板。"""
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "缺少 file 字段"}), 400
    name = _secure_filename(f.filename or "template.md")
    save_path = _USER_TEMPLATE_DIR / name
    f.save(save_path)
    return jsonify({"ok": True, "name": name, "format": _fmt_of(save_path)})


# --------- 报告：生成 + 预览 + 下载 ---------
_REPORT_CACHE: dict[str, dict] = {}
_REPORT_JOBS: dict[str, dict] = {}  # job_id -> {stage, percent, message, status, error, report_id}


def _report_dir(paper_id: str) -> _Path:
    """单个 paper 的报告持久化目录。

    注意：不能用 werkzeug.secure_filename —— 它会把中文 utf-8 字节做
    ASCII-encode，导致所有 2025xxx 试卷都被映射到同一个安全短名。
    改为只替换文件系统明确不允许的字符（/、\、NUL、控制字符），
    中文、空格、点、横线等都保留。
    """
    s = _safe_path_segment(paper_id) or "unknown"
    d = PAPERS_DIR / s / "feedback"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe_path_segment(name: str) -> str:
    """把任意 paper_id 转成可在文件系统中作为单个目录段使用的字符串。
    - 保留中文、空格、点、横线等
    - 替换 / \\ : * ? \" < > | 控制字符为空字符串
    """
    if not name:
        return ""
    out_chars = []
    for ch in name:
        if ch in ('/', '\\', ':', '*', '?', '"', '<', '>', '|') or ord(ch) < 32:
            continue
        out_chars.append(ch)
    s = "".join(out_chars).strip().rstrip(".")
    return s


def _persist_report(payload: dict) -> None:
    """把内存里的 report payload 落到磁盘：
    <paper_id>/feedback/<report_id>.json  + 可选 .docx / .pdf。"""
    try:
        d = _report_dir(payload["paper_id"])
        meta = {
            "report_id": payload["report_id"],
            "paper_id": payload["paper_id"],
            "paper_name": payload["paper_name"],
            "report": payload["report"],
            "md": payload["md"],
            "_created_at": payload.get("_created_at") or time.time(),
        }
        (d / f"{payload['report_id']}.json").write_text(
            json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        if payload.get("_docx_bytes"):
            (d / f"{payload['report_id']}.docx").write_bytes(payload["_docx_bytes"])
        if payload.get("_pdf_bytes"):
            (d / f"{payload['report_id']}.pdf").write_bytes(payload["_pdf_bytes"])
    except Exception as e:
        # 落盘失败不影响主流程
        print(f"[feedback] 持久化失败 {payload.get('report_id')}: {e}", flush=True)


def _load_report_from_disk(report_id: str) -> dict | None:
    """按 report_id 在所有 paper/feedback 目录下查找报告元数据 + 二进制。"""
    if not PAPERS_DIR.exists():
        return None
    for meta_path in PAPERS_DIR.glob("*/feedback/*.json"):
        if meta_path.stem != report_id:
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        d = meta_path.parent
        payload = dict(meta)
        payload["_docx_bytes"] = (d / f"{report_id}.docx").read_bytes() if (d / f"{report_id}.docx").exists() else None
        payload["_pdf_bytes"] = (d / f"{report_id}.pdf").read_bytes() if (d / f"{report_id}.pdf").exists() else None
        return payload
    return None


def _delete_report_from_disk(report_id: str) -> bool:
    if not PAPERS_DIR.exists():
        return False
    for meta_path in PAPERS_DIR.glob("*/feedback/*.json"):
        if meta_path.stem != report_id:
            continue
        d = meta_path.parent
        try:
            for ext in (".json", ".docx", ".pdf"):
                p = d / f"{report_id}{ext}"
                if p.exists():
                    p.unlink()
        except Exception as e:
            print(f"[feedback] 删除失败 {report_id}: {e}", flush=True)
            return False
        return True
    return False


def _list_reports_for_paper(paper_id: str) -> list[dict]:
    """列出某 paper 下所有已落盘报告。

    注意：扫盘用全目录 glob（*/feedback/*.json），再按 meta.paper_id
    严格过滤。这样即便文件名用的安全短名跟 paper_id 不一致
    （旧版本 bug 已留盘），仍能正确归类。
    """
    target = (paper_id or "").strip()
    out = []
    if not PAPERS_DIR.exists():
        return out
    seen_ids: set[str] = set()
    # 先扫所有 paper 的 feedback 目录
    for meta_path in PAPERS_DIR.glob("*/feedback/*.json"):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        meta_pid = (meta.get("paper_id") or "").strip()
        if target and meta_pid != target:
            continue
        rid = meta.get("report_id")
        if not rid or rid in seen_ids:
            # 同一 report_id（不同目录里残留的同名文件）只保留一份
            continue
        seen_ids.add(rid)
        rpt = (meta.get("report") or {})
        out.append({
            "report_id": rid,
            "paper_id": meta_pid,
            "paper_name": meta.get("paper_name"),
            "total_score": rpt.get("total_score"),
            "avg_total_score": rpt.get("avg_total_score"),
            "ts": meta.get("_created_at"),
        })
    out.sort(key=lambda x: x.get("ts") or 0, reverse=True)
    return out


def _job_update(job_id: str, **kw) -> None:
    job = _REPORT_JOBS.setdefault(job_id, {
        "stage": "init", "percent": 0, "message": "排队中…",
        "status": "running", "error": None, "report_id": None,
    })
    job.update(kw)


def _run_fb_build(job_id: str, *, paper_id: str, paper_name: str,
                  excel_path: str, md_path: str, docx_path: str | None,
                  teacher: str, class_name: str, n_students: int) -> None:
    try:
        result = _fb_builder.build(
            paper_id=paper_id,
            paper_name=paper_name,
            excel_path=excel_path,
            md_template_path=md_path,
            docx_template_path=docx_path,
            teacher=teacher,
            class_name=class_name,
            n_students=n_students,
            papers_dir=PAPERS_DIR,
            on_stage=lambda stage, pct, msg: _job_update(
                job_id, stage=stage, percent=pct, message=msg,
            ),
        )
        payload = {
            "report_id": result.report_id,
            "paper_id": paper_id,
            "paper_name": paper_name,
            "report": result.report.to_dict(),
            "md": result.md,
            "_docx_bytes": result.docx_bytes,
            "_pdf_bytes": result.pdf_bytes,
            "_created_at": time.time(),
        }
        _REPORT_CACHE[result.report_id] = payload
        _persist_report(payload)
        _job_update(job_id, status="done", report_id=result.report_id,
                    stage="done", percent=100, message="生成完成")
    except Exception as e:
        _job_update(job_id, status="error", error=str(e),
                    stage="error", message=f"生成失败：{e}")


@app.route("/api/feedback/reports", methods=["POST"])
def feedback_generate_report():
    """提交生成任务，返回 job_id。前端轮询 /progress。"""
    paper_id = request.form.get("paper_id", "").strip()
    if not paper_id:
        return jsonify({"error": "缺少 paper_id"}), 400
    paper_dir = PAPERS_DIR / paper_id
    if not (paper_dir / "paper.json").exists():
        return jsonify({"error": f"未找到试卷：{paper_id}"}), 404

    excel_file = request.files.get("excel")
    if not excel_file:
        return jsonify({"error": "缺少 excel 字段"}), 400
    excel_path = PAPERS_DIR / "_uploads" / f"_fb_{int(time.time()*1000)}_{_secure_filename(excel_file.filename or 'stats.xlsx')}"
    excel_path.parent.mkdir(parents=True, exist_ok=True)
    excel_file.save(excel_path)

    teacher = request.form.get("teacher", "")
    class_name = request.form.get("class_name", "")
    # 参考人数不再从前端入参读取，强制从 Excel class_meta 解析

    md_name = request.form.get("md_template") or _DEFAULT_MD_NAME
    docx_name = request.form.get("docx_template") or _DEFAULT_DOCX_NAME
    md_path = _resolve_template(md_name)
    docx_path = _resolve_template(docx_name) if docx_name else None
    if not md_path:
        return jsonify({"error": f"未找到 md 模板：{md_name}"}), 404

    try:
        paper_json = json.loads((paper_dir / "paper.json").read_text(encoding="utf-8"))
        paper_name = (paper_json.get("source") or {}).get("name") or paper_id
    except Exception as e:
        return jsonify({"error": f"读取 paper.json 失败：{e}"}), 500

    job_id = f"fbj_{uuid.uuid4().hex[:12]}"
    _job_update(job_id, stage="init", percent=0, message="排队中…",
                status="running", error=None, report_id=None)
    threading.Thread(
        target=_run_fb_build,
        args=(job_id,),
        kwargs=dict(
            paper_id=paper_id, paper_name=paper_name,
            excel_path=str(excel_path), md_path=md_path, docx_path=docx_path,
            teacher=teacher, class_name=class_name, n_students=0,
        ),
        daemon=True,
    ).start()

    return jsonify({"job_id": job_id, "report_id": None, "status": "running"})


@app.route("/api/feedback/reports/progress/<job_id>", methods=["GET"])
def feedback_report_progress(job_id: str):
    """轮询生成进度。status: running | done | error"""
    job = _REPORT_JOBS.get(job_id)
    if not job:
        return jsonify({"error": "job 不存在", "status": "error"}), 404
    return jsonify({
        "job_id": job_id,
        "stage": job.get("stage"),
        "percent": int(job.get("percent") or 0),
        "message": job.get("message") or "",
        "status": job.get("status"),
        "error": job.get("error"),
        "report_id": job.get("report_id"),
    })


# 保留旧路径以防有外部调用：GET /reports?job_id=xxx 也能直接拿到产物
@app.route("/api/feedback/reports/by-job/<job_id>", methods=["GET"])
def feedback_get_report_by_job(job_id: str):
    job = _REPORT_JOBS.get(job_id)
    if not job or not job.get("report_id"):
        return jsonify({"error": "尚未完成"}), 404
    return feedback_get_report(job["report_id"])


@app.route("/api/feedback/reports/<report_id>", methods=["GET"])
def feedback_get_report(report_id: str):
    payload = _REPORT_CACHE.get(report_id) or _load_report_from_disk(report_id)
    if not payload:
        return jsonify({"error": "报告不存在或已过期"}), 404
    _REPORT_CACHE[report_id] = payload
    return jsonify({
        "report_id": payload["report_id"],
        "paper_id": payload["paper_id"],
        "paper_name": payload["paper_name"],
        "report": payload["report"],
        "md": payload["md"],
        "has_docx": payload["_docx_bytes"] is not None,
        "has_pdf": payload["_pdf_bytes"] is not None,
    })


@app.route("/api/feedback/reports/list", methods=["GET"])
def feedback_list_reports():
    """GET /api/feedback/reports/list?paper_id=xxx

    按 paper_id 列出已落盘报告；省略 paper_id 时返回所有报告。
    """
    paper_id = (request.args.get("paper_id") or "").strip()
    if not PAPERS_DIR.exists():
        return jsonify({"reports": []})
    if paper_id:
        items = _list_reports_for_paper(paper_id)
    else:
        items = _list_reports_for_paper("")  # 空 paper_id：glob 全扫盘 + 不过滤
    items.sort(key=lambda x: x.get("ts") or 0, reverse=True)
    return jsonify({"reports": items})


@app.route("/api/feedback/reports/<report_id>", methods=["DELETE"])
def feedback_delete_report(report_id: str):
    """删除磁盘上的报告（json + docx + pdf 三件套）。"""
    _REPORT_CACHE.pop(report_id, None)
    ok = _delete_report_from_disk(report_id)
    if not ok:
        return jsonify({"error": "报告不存在或删除失败"}), 404
    return jsonify({"ok": True, "report_id": report_id})


@app.route("/api/feedback/reports/<report_id>/download", methods=["GET"])
def feedback_download_report(report_id: str):
    """GET /api/feedback/reports/<id>/download?format=md|docx|pdf"""
    payload = _REPORT_CACHE.get(report_id) or _load_report_from_disk(report_id)
    if not payload:
        return jsonify({"error": "报告不存在或已过期"}), 404
    _REPORT_CACHE[report_id] = payload
    fmt = (request.args.get("format") or "md").lower()
    raw_name = f"{payload['paper_name']}_教学反馈报告.{fmt}"
    # 注意 \w 在 Python 3 默认是 unicode，需要 re.ASCII 才把中文当作非 \w 替换
    safe_ascii = _re.sub(r"[^\w.-]", "_", raw_name, flags=_re.ASCII)
    # RFC 5987 编码中文名，部分浏览器会优先用 filename*，老客户端用 filename
    from urllib.parse import quote as _quote
    encoded_name = _quote(raw_name, safe='')
    disposition = (
        f'attachment; filename="{safe_ascii}"; '
        f"filename*=UTF-8''{encoded_name}"
    )
    if fmt == "md":
        return Response(payload["md"], mimetype="text/markdown; charset=utf-8",
                        headers={"Content-Disposition": disposition})
    if fmt == "docx":
        if not payload["_docx_bytes"]:
            return jsonify({"error": "docx 不可用（模板渲染失败）"}), 400
        resp = send_file(_io.BytesIO(payload["_docx_bytes"]), as_attachment=True,
                         download_name=safe_ascii,
                         mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        # 覆盖 header，加入 RFC 5987 中文名（send_file 默认 download_name 不带 filename*）
        resp.headers["Content-Disposition"] = disposition
        return resp
    if fmt == "pdf":
        if not payload["_pdf_bytes"]:
            return jsonify({"error": "pdf 不可用"}), 400
        resp = send_file(_io.BytesIO(payload["_pdf_bytes"]), as_attachment=True,
                         download_name=safe_ascii, mimetype="application/pdf")
        resp.headers["Content-Disposition"] = disposition
        return resp
    return jsonify({"error": f"未知格式：{fmt}"}), 400


# --------------------------------------------------------------- main
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    print(f"[server] http://{args.host}:{args.port}", flush=True)
    print(f"[server] papers dir: {PAPERS_DIR}", flush=True)
    # threaded=True 让 SSE 与 PUT 等请求并行
    app.run(host=args.host, port=args.port, debug=args.debug, threaded=True)


if __name__ == "__main__":
    main()
