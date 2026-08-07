"""qwen 客户端 + JSON 抽取。

该模块只提供 **不强制依赖 accelerate 的** 加载方式（``model.to("cuda")`` 单卡写法），
这样既能在 paddleocr-vl / lighthouse 这种没有 accelerate 的环境跑，也能在 word_cutter
环境下跑。

设计要点：

- 单例 ``QwenClient``：避免每次重新加载（Qwen2.5-3B bf16 加载 ≈ 6GB）；
- ``extract_for_question`` 接受 ``NormalizedQuestion`` 风格的数据，返回标准化 JSON；
- ``_parse_json_object`` 能从模型输出里抠出第一个合法 JSON 对象（兼容 ```json ... ```、前后解释性文字、
  嵌入换行/逗号错位等常见不规范形态）；
- ``_fallback_analysis`` 在所有重试都失败时，返回带 ``reason`` 的退化结构，避免上层脚本中断；
- 接口与 ``paper.v0.1`` **解耦**：输入只依赖 dict，不直接 ``import`` 契约，方便后续替换。
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any


DEFAULT_MODEL_PATH = "/home/dataset/yjk_data/Qwen"
DEFAULT_DEVICE = os.environ.get("QWEN_DEVICE", "cuda:2")
DEFAULT_MAX_NEW_TOKENS = int(os.environ.get("QWEN_MAX_NEW_TOKENS", "256"))
DEFAULT_TEMPERATURE = float(os.environ.get("QWEN_TEMPERATURE", "0.2"))
DEFAULT_TOP_P = float(os.environ.get("QWEN_TOP_P", "0.9"))


SYSTEM_PROMPT = """你是中国初中数学命题与教学专家，专注于分析中考数学试题所考察的知识点。

任务：对每道题目给出结构化的“知识点提炼”，要求：
1. 提炼 1～4 个具体数学概念/定理/方法（不要写成太宽泛的“几何”“代数”）；
2. 用“学生能听懂”的语言给出 ≤30 字的解析依据，指出题中哪一处条件或设问考察了这些知识点；
3. confidence 是 0～1 的小数，反映模型对该题目知识点判定把握程度（不允许是 1.0，除非题面非常明确）。

严格按以下 JSON 输出，不要添加任何额外说明或 markdown 包裹：

{
  "knowledge_points": ["知识点1", "知识点2"],
  "reasoning": "≤30 字说明",
  "confidence": 0.85
}"""


_USER_PROMPT_TEMPLATE = """【题目类型】{qtype}
【题面】{stem}
【选项】{options_text}
【答案】{answer}
【官方解析（仅参考）】{solution}
【满分】{full_score}

请提炼本道题考察的数学知识点（1～4 项），输出 JSON。"""


@dataclass
class QwenConfig:
    model_path: str = DEFAULT_MODEL_PATH
    device: str = DEFAULT_DEVICE
    max_new_tokens: int = DEFAULT_MAX_NEW_TOKENS
    temperature: float = DEFAULT_TEMPERATURE
    top_p: float = DEFAULT_TOP_P


class QwenClient:
    """Qwen 推理客户端（懒加载单例）。"""

    _instance: "QwenClient | None" = None

    def __init__(self, config: QwenConfig | None = None) -> None:
        import torch  # 延迟导入，避免副作用
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self.config = config or QwenConfig()

        # 兼容 CUDA device 形式：cuda / cuda:0 都允许
        requested = self.config.device
        if requested.startswith("cuda") and not torch.cuda.is_available():
            raise RuntimeError(
                f"请求运行在 {requested}，但当前 torch 报 cuda 不可用；"
                "请检查驱动/CUDA 安装，或切到 cpu:0"
            )
        if requested.startswith("cuda") and torch.cuda.is_available():
            count = torch.cuda.device_count()
            if ":" in requested:
                idx = int(requested.split(":", 1)[1])
                if idx >= count:
                    raise RuntimeError(
                        f"请求 {requested}，但只有 {count} 张 GPU；"
                        f"请设置 QWEN_DEVICE=cuda:0～{count - 1}"
                    )

        torch_dtype = torch.bfloat16 if requested.startswith("cuda") else torch.float32

        self._torch = torch
        self.tokenizer = AutoTokenizer.from_pretrained(self.config.model_path)
        model = AutoModelForCausalLM.from_pretrained(
            self.config.model_path,
            torch_dtype=torch_dtype,
        )
        model = model.to(requested)
        model.eval()
        self.model = model

    # ---------------- classmethod 单例 -----------------
    @classmethod
    def get(cls, config: QwenConfig | None = None) -> "QwenClient":
        if cls._instance is None:
            cls._instance = cls(config)
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """主进程结束后释放单例，下一次重新加载。"""
        cls._instance = None

    # ---------------- 内部生成 -----------------
    def _generate(self, messages: list[dict]) -> str:
        import torch

        text = self.tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        inputs = self.tokenizer(text, return_tensors="pt").to(self.model.device)
        with torch.inference_mode():
            out = self.model.generate(
                **inputs,
                max_new_tokens=self.config.max_new_tokens,
                do_sample=self.config.temperature > 0,
                temperature=self.config.temperature,
                top_p=self.config.top_p,
                repetition_penalty=1.05,
                pad_token_id=self.tokenizer.eos_token_id,
            )
        new_tokens = out[0][inputs.input_ids.shape[1]:]
        return self.tokenizer.decode(new_tokens, skip_special_tokens=True).strip()

    # ---------------- 题目级提炼 -----------------
    def extract_for_question(self, question: dict[str, Any]) -> dict[str, Any]:
        """对单道题进行知识点提炼，输出标准化分析。

        输入：与 ``NormalizedQuestion`` schema 对齐的 dict（仅使用读得到的字段）。
        输出：dict，字段为 ``knowledge_points / reasoning / confidence``，附带元数据。
        """
        prompt = _build_user_prompt(question)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]

        attempts: list[dict[str, Any]] = []
        last_error: str | None = None
        last_raw: str | None = None

        # 第一次主尝试 + 一次修复尝试（如果第一次 JSON 解析失败，把同样 output 喂回去让模型修正）
        for step in range(2):
            output = self._generate(messages)
            attempts.append({"step": step, "raw": output})
            last_raw = output
            parsed = _parse_json_object(output)
            if parsed is not None and _validate_extraction(parsed):
                cleaned = _normalize_extraction(parsed, source_step=step)
                cleaned["raw_outputs"] = attempts
                return cleaned
            last_error = "json_parse_or_validation_failed"

        # 退化结构：保留原始输出，方便人工核对；上层脚本可根据 confidence==0 决定是否跳过
        return {
            "knowledge_points": [],
            "reasoning": "",
            "confidence": 0.0,
            "model": self.config.model_path,
            "status": "fallback",
            "reason": last_error or "unknown",
            "raw_output": last_raw,
            "raw_outputs": attempts,
        }


# ----------- helper: 题目渲染 -----------

def _build_user_prompt(question: dict[str, Any]) -> str:
    qtype = question.get("question_type", "unknown")
    stem = (question.get("stem_text") or question.get("stem_markdown") or "").strip()
    options = question.get("options") or []
    if isinstance(options, list) and options and isinstance(options[0], dict):
        # 兼容 dict / object 两种形态
        option_lines: list[str] = []
        for opt in options:
            try:
                label = opt.get("label", "")
                text = (opt.get("text") or "").strip()
            except AttributeError:
                label = getattr(opt, "label", "")
                text = (getattr(opt, "text", "") or "").strip()
            if not text:
                continue
            option_lines.append(f"{label}. {text}")
        options_text = "\n".join(option_lines) if option_lines else "（无）"
    else:
        options_text = "（无）"

    answer = str(question.get("answer") or "").strip() or "（未提供）"
    solution = (question.get("solution") or "").strip() or "（未提供）"
    full_score = question.get("full_score")
    full_score_text = (
        str(full_score) if full_score not in (None, "") else "（未提供）"
    )

    return _USER_PROMPT_TEMPLATE.format(
        qtype=qtype,
        stem=stem,
        options_text=options_text,
        answer=answer,
        solution=solution,
        full_score=full_score_text,
    )


# ----------- helper: JSON 抽取 -----------

_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", re.IGNORECASE)
# 找首个顶层 { 的启发式，正则 *极短* 仅用于定位起点，不负责配对
_JSON_OBJECT_START_RE = re.compile(r"\{", re.MULTILINE)


def _find_top_level_json_objects(text: str) -> list[str]:
    """逐字符扫描找到所有顶层 {...} JSON 对象。

    不依赖正则 ``\\{[\\s\\S]*\\}``——后者遇到 LaTeX、转义括号、注释里残留的
    ``{`` / ``}`` 就会切歪。改为严格的括号配对 + 字符串状态机。
    """
    results: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c != "{":
            i += 1
            continue
        # 从当前 { 开始做括号配对，同时跳过 JSON 字符串内部
        depth = 0
        j = i
        in_string = False
        escape = False
        while j < n:
            ch = text[j]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                j += 1
                continue
            if ch == '"':
                in_string = True
                j += 1
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    results.append(text[i : j + 1])
                    i = j + 1
                    break
            j += 1
        else:
            # 没找到匹配的右括号，停止扫描
            break
    return results


def _escape_orphan_backslashes(s: str) -> str:
    """把 JSON 字符串里 ``\\X`` 中 X 不是合法 JSON 转义字符的反斜杠转义修正成 ``\\\\X``。

    JSON 字符串里 ``\`` 后面必须是 " \\ " / " " / " \\\\ " / " \\/ " / " \\b " /
    " \\f " / " \\n " / " \\r " / " \\t " / " \\uXXXX " 之一，否则 ``json.loads`` 抛
    ``Invalid \\escape``。大模型经常吐出含 LaTeX 命令（如 ``\\overrightarrow`` 、
    ``\\sqrt``、``\\frac``）的字符串，引发解析失败。这层修复保留语义：解析后
    再 ``str(...)`` 时，这些位置会显示成两个反斜杠+字母，与原意只有 1 个反斜杠的
    LaTeX 字符串相比会有偏差——但这层偏差只影响**字段值的渲染**（reasoning 字
    段），不破坏 schema 结构。下游消费方在显示时可以用 ``.replace('\\\\\\\\', '
    \\\\')`` 做归一化（如果在意完美保真）。
    """
    # \X 中 X 不是合法 JSON 转义字符，则把 \ 改成 \\
    return re.sub(r'\\(?![\\"/bfnrtu])', r'\\\\', s)


def _try_load_json_obj(s: str) -> dict | None:
    """尝试加载一段 JSON 文本为对象，多轮容错。"""
    cleaned = s.strip()
    # 容错 1：去掉对象/数组末尾的逗号
    cleaned = re.sub(r",(\s*[}\]])", r"\1", cleaned)

    # 直接尝试
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        data = None

    if isinstance(data, dict):
        return data

    # 容错 2：尝试把 JSON 字符串中的孤立反斜杠转义修正（兼容 LaTeX 文本）
    fixed = _escape_orphan_backslashes(cleaned)
    if fixed != cleaned:
        try:
            data = json.loads(fixed)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict):
            return data

    # 容错 3：逐位置截取 {}，尝试 `json.loads(candidate)` —— 针对大模型把 JSON
    # 之外的解释性文字混在吐出的同一段文本里的情况（罕见）
    for start in range(0, len(cleaned)):
        if cleaned[start] != "{":
            continue
        for end in range(len(cleaned), start, -1):
            if cleaned[end - 1] != "}":
                continue
            try:
                data = json.loads(cleaned[start:end])
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                return data
    return None


def _parse_json_object(text: str) -> dict | None:
    if not text:
        return None

    # 1) 优先抓 ```json ... ``` 围栏里的 JSON
    block = _JSON_BLOCK_RE.search(text)
    if block:
        obj = _try_load_json_obj(block.group(1))
        if obj is not None:
            return obj

    # 2) 顶层 {...} 扫描（括号配对 + 字符串状态机），逐个尝试
    for candidate in _find_top_level_json_objects(text):
        obj = _try_load_json_obj(candidate)
        if obj is not None:
            return obj

    return None


def _validate_extraction(obj: dict) -> bool:
    if not isinstance(obj, dict):
        return False
    if "knowledge_points" not in obj:
        return False
    if "reasoning" not in obj:
        return False
    if "confidence" not in obj:
        return False
    kp = obj["knowledge_points"]
    if not isinstance(kp, list) or not all(isinstance(x, str) for x in kp):
        return False
    if not isinstance(obj["reasoning"], str):
        return False
    conf = obj["confidence"]
    if isinstance(conf, str):
        try:
            conf = float(conf)
        except ValueError:
            return False
    if not isinstance(conf, (int, float)):
        return False
    return 0.0 <= float(conf) <= 1.0


def _normalize_extraction(obj: dict, source_step: int) -> dict[str, Any]:
    kp = [str(x).strip() for x in obj.get("knowledge_points", []) if str(x).strip()]
    reasoning = str(obj.get("reasoning", "")).strip()
    try:
        confidence = float(obj.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, round(confidence, 2)))

    return {
        "knowledge_points": kp,
        "reasoning": reasoning,
        "confidence": confidence,
        "model": DEFAULT_MODEL_PATH,
        "status": "ok" if confidence > 0 else "low_confidence",
        "parse_step": source_step,
    }


# 直接命令行调试入口：python -m campus_p2_core.p2_stage_5.knowledge_extractor
if __name__ == "__main__":
    demo_question = {
        "question_type": "single_choice",
        "stem_text": "下列4个汉字中，从数学的角度可以看作轴对称图形的是（ ）",
        "options": [
            {"label": "A", "text": "智"},
            {"label": "B", "text": "慧"},
            {"label": "C", "text": "美"},
            {"label": "D", "text": "勇"},
        ],
        "answer": "C",
        "solution": "若一个图形沿一条直线折叠后两部分能完全重合，则为轴对称图形。",
        "full_score": 3,
    }
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--device", default=DEFAULT_DEVICE)
    parser.add_argument("--model-path", default=DEFAULT_MODEL_PATH)
    parser.add_argument("--max-new-tokens", type=int, default=DEFAULT_MAX_NEW_TOKENS)
    args = parser.parse_args()

    cfg = QwenConfig(
        model_path=args.model_path,
        device=args.device,
        max_new_tokens=args.max_new_tokens,
        temperature=0.2,
    )
    client = QwenClient.get(cfg)
    result = client.extract_for_question(demo_question)
    print(json.dumps(result, ensure_ascii=False, indent=2))
