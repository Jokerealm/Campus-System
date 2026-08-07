"""调用本地 Qwen2.5-VL 模型（kex.QwenClient）生成教学分析文本。

提供两个能力：
- knowledge_analysis: 薄弱知识点分析（Markdown）
- teaching_advice: 教学建议（Markdown）

直接加载 kex.QwenClient，独占 cuda:2，不依赖 app.py。
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# ── kex 路径（与 app.py 保持一致）──────────────────────────────────────────

_ROOT = Path(__file__).resolve().parents[3]
_WORD_CUTTER_ROOT = _ROOT / "word_cutter_system"
if str(_WORD_CUTTER_ROOT) not in sys.path:
    sys.path.insert(0, str(_WORD_CUTTER_ROOT))

from campus_p2_core.p2_stage_5 import knowledge_extractor as _kex

_DEVICE = os.environ.get("QWEN_DEVICE", "cuda:2")
_MAX_TOKENS = int(os.environ.get("QWEN_MAX_NEW_TOKENS", "1500"))
_TEMPERATURE = 0.4

# 懒加载单例
_qwen_client: _kex.QwenClient | None = None


def _get_client() -> _kex.QwenClient:
    global _qwen_client
    if _qwen_client is None:
        cfg = _kex.QwenConfig(device=_DEVICE, max_new_tokens=_MAX_TOKENS, temperature=_TEMPERATURE)
        print(f"[llm_report] loading Qwen on {_DEVICE}...", flush=True)
        _qwen_client = _kex.QwenClient.get(cfg)
        print(f"[llm_report] model loaded to {_qwen_client.model.device}", flush=True)
    return _qwen_client


# ── 提示词构建 ──────────────────────────────────────────────────────────────

def _build_prompt_knowledge(weak_items: list[dict[str, Any]]) -> str:
    rows = []
    for i, q in enumerate(weak_items, 1):
        rows.append(
            f"{i}. 第{q['no']}题 ({q.get('qtype','?')}, 难度 {q.get('difficulty','?')}, 错题率 {q['error_rate']*100:.1f}%)\n"
            f"   典型错误：{q.get('typical_error','-') or '-'}"
        )
    body = "\n".join(rows) if rows else "（无）"
    return (
        "你是一名资深中学数学教师。以下是某班级本次考试中错题率最高的 5 道题，"
        "以及它们的典型错误描述。请生成中文 Markdown 格式的「薄弱知识点分析」，"
        "要求：\n"
        "1. 按错题率从高到低列出 5 个最薄弱知识点；\n"
        "2. 每个知识点说明：考察内容、典型失分原因、对应的教学补救策略；\n"
        "3. 用 `## 二、薄弱知识点分析` 作为一级标题，3-5 条 `###` 三级标题子项；\n"
        "4. 不要 JSON、不要解释性前缀，只输出 Markdown 正文。\n\n"
        f"薄弱题数据：\n{body}\n"
    )


def _build_prompt_advice(qtype_agg: list[dict[str, Any]], overall: dict[str, Any]) -> str:
    body_qt = "\n".join(
        f"- {r['qtype']}（{r['count']} 题）平均错题率 {r['avg_error_rate']*100:.1f}%，班级均分 {r['avg_score']}"
        for r in qtype_agg
    ) or "- （无）"
    return (
        "你是一名资深中学数学教师。基于本次班级考试的整体数据和按题型的错题率统计，"
        "生成中文 Markdown 格式的「教学建议」，要求分三段：\n\n"
        "### 集体补救\n针对共性薄弱点给出 2-3 条可立即落地的补救措施。\n\n"
        "### 分层作业\n针对高/中/低三个层次分别布置一次课后作业建议（每层 1 条）。\n\n"
        "### 下次复习重点\n按重要度列出 3 个下一次课优先复习的知识点或题型。\n\n"
        "用 `## 三、教学建议` 作为一级标题。不要 JSON、不要其他解释。\n\n"
        f"整体数据：参考 {overall.get('n_students', 0)} 人，"
        f"总分 {overall.get('total_score', 0)} 分，"
        f"班级均分 {overall.get('avg_total_score', 0)}。\n\n"
        f"按题型：\n{body_qt}\n"
    )


# ── Mock ────────────────────────────────────────────────────────────────────

def _mock_knowledge(weak_items: list[dict[str, Any]]) -> str:
    rows = []
    for i, q in enumerate(weak_items, 1):
        rows.append(
            f"### {i}. 第{q['no']}题 · 错题率 {q['error_rate']*100:.1f}%\n"
            f"- **考察内容**：{q.get('qtype','?')}（难度 {q.get('difficulty','?')}）\n"
            f"- **典型失分**：{q.get('typical_error') or '概念不清、计算失误'}\n"
            f"- **补救策略**：课堂针对性讲解 + 同类变式 5 道 + 个别面批\n"
        )
    body = "\n".join(rows) if rows else "_本次考试无显著薄弱题。_"
    return (
        "## 二、薄弱知识点分析\n\n"
        "（*LLM 服务暂不可用，以下为基于模板生成的占位文本。*）\n\n"
        f"{body}\n"
    )


def _mock_advice(qtype_agg: list[dict[str, Any]], overall: dict[str, Any]) -> str:
    if qtype_agg:
        worst = qtype_agg[0]
        worst_line = f"本次考试 **{worst['qtype']}** 平均错题率最高（{worst['avg_error_rate']*100:.1f}%），需重点关注。"
    else:
        worst_line = ""
    return (
        "## 三、教学建议\n\n"
        "（*LLM 服务暂不可用，以下为占位文本。*）\n\n"
        f"{worst_line}\n\n"
        "### 集体补救\n"
        "- 用一节课集中讲解错题率前 3 题，统一订正；\n"
        "- 课堂限时小测 15 分钟，巩固易混淆点。\n\n"
        "### 分层作业\n"
        "- 高分层：综合题 3 道，训练多步骤推理；\n"
        "- 中等层：错题同类变式 5 道；\n"
        "- 后进层：基础概念填空 10 题 + 计算练习 10 题。\n\n"
        "### 下次复习重点\n"
        "- 本次错题率最高题型；\n"
        "- 学生在「典型错误」中暴露的概念盲点；\n"
        "- 计算准确率与书写规范。\n"
    )


# ── LLM 调用 ────────────────────────────────────────────────────────────────

def _call_qwen(prompt: str) -> str | None:
    try:
        client = _get_client()
        messages = [
            {"role": "system", "content": "你是资深中学数学教师，输出严谨中文 Markdown。"},
            {"role": "user", "content": prompt},
        ]
        return client._generate(messages)
    except Exception as e:
        log.warning("[llm_report] Qwen 调用失败: %s", e)
        return None


# ── 公开 API ────────────────────────────────────────────────────────────────

def generate_knowledge_analysis(weak_items: list[dict[str, Any]]) -> str:
    out = _call_qwen(_build_prompt_knowledge(weak_items))
    return out if out else _mock_knowledge(weak_items)


def generate_teaching_advice(qtype_agg: list[dict[str, Any]], overall: dict[str, Any]) -> str:
    out = _call_qwen(_build_prompt_advice(qtype_agg, overall))
    return out if out else _mock_advice(qtype_agg, overall)
