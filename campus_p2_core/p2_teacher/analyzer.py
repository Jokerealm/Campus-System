from __future__ import annotations

from pathlib import Path

from campus_p2_core.contracts.p2 import (
    KnowledgeDiagnostic,
    P2ExamAnalysis,
    P3SearchRequest,
    QuestionAnalysis,
    ScoreRecord,
    TeachingReport,
)
from campus_p2_core.contracts.paper import KnowledgeCandidate, NormalizedPaper, NormalizedQuestion
from campus_p2_core.p1_input.normalized_paper import load_normalized_paper
from campus_p2_core.p2_teacher.score_loader import load_score_records


FALLBACK_KNOWLEDGE_RULES: list[tuple[tuple[str, ...], tuple[str, str]]] = [
    (("导数", "极值", "恒成立"), ("KP-FUNC-DERIV-002", "利用导数研究单调性与极值")),
    (("导数", "参数"), ("KP-FUNC-DERIV-003", "导数中的参数与恒成立问题")),
    (("椭圆",), ("KP-GEO-ANALYTIC-003", "椭圆")),
    (("双曲线",), ("KP-GEO-ANALYTIC-004", "双曲线")),
    (("圆锥曲线", "弦", "最值"), ("KP-GEO-ANALYTIC-006", "圆锥曲线中的弦与最值")),
    (("数列", "递推"), ("KP-ALG-SEQUENCE-003", "数列递推与通项求法")),
    (("数列", "求和"), ("KP-ALG-SEQUENCE-004", "数列求和方法")),
    (("向量",), ("KP-GEO-VECTOR-002", "平面向量数量积")),
    (("三角函数",), ("KP-FUNC-TRIG-002", "三角函数图像与性质")),
    (("三角恒等",), ("KP-FUNC-TRIG-003", "三角恒等变换")),
    (("概率", "分布列"), ("KP-STAT-RV-001", "离散型随机变量分布列")),
    (("期望", "方差"), ("KP-STAT-RV-002", "数学期望与方差")),
    (("样本", "平均数", "中位数", "众数"), ("KP-STAT-BASIC-002", "样本数字特征")),
    (("一次函数",), ("MATH.8.FUNC.001", "一次函数图像与性质")),
    (("函数关系式",), ("MATH.8.FUNC.002", "一次函数实际应用")),
    (("方程", "不等式"), ("MATH.7.EQ.001", "一元一次方程")),
    (("三角形", "全等"), ("MATH.8.GEO.001", "三角形全等")),
    (("三边关系",), ("MATH.8.GEO.002", "三角形三边关系")),
    (("圆",), ("MATH.9.GEO.001", "圆的基本性质")),
]


def analyze_exam(
    paper_json_path: str | Path,
    score_file_path: str | Path,
    exam_id: str = "exam_demo_001",
    class_name: str = "高二3班",
) -> P2ExamAnalysis:
    paper = load_normalized_paper(paper_json_path)
    scores = load_score_records(score_file_path)
    return analyze_exam_records(paper, scores, exam_id=exam_id, class_name=class_name)


def analyze_exam_records(
    paper: NormalizedPaper,
    scores: list[ScoreRecord],
    exam_id: str,
    class_name: str,
) -> P2ExamAnalysis:
    question_by_no = {_normalize_question_no(q.question_no): q for q in paper.questions}
    warnings: list[str] = []
    analyses: list[QuestionAnalysis] = []

    for score in scores:
        normalized_no = _normalize_question_no(score.question_no)
        question = question_by_no.get(normalized_no)
        if question is None:
            warnings.append(f"成绩文件中的题号 {score.question_no} 未在规范化试卷中找到")
        analyses.append(_build_question_analysis(score, question))

    score_nos = {_normalize_question_no(score.question_no) for score in scores}
    for question in paper.questions:
        if _normalize_question_no(question.question_no) not in score_nos:
            warnings.append(f"试卷题号 {question.question_no} 缺少成绩数据")

    diagnostics = _build_knowledge_diagnostics(analyses)
    p3_requests = _build_p3_search_requests(diagnostics, analyses)
    knowledge_tag_coverage = _knowledge_tag_coverage(analyses)
    teaching_report = _build_teaching_report(paper, class_name, analyses, diagnostics, knowledge_tag_coverage)

    return P2ExamAnalysis(
        exam_id=exam_id,
        paper_id=paper.paper_id,
        class_name=class_name,
        knowledge_tag_coverage=knowledge_tag_coverage,
        question_analysis=sorted(analyses, key=lambda item: (_severity_rank(item.severity), item.score_rate)),
        knowledge_diagnostics=diagnostics,
        p3_search_requests=p3_requests,
        teaching_report=teaching_report,
        warnings=warnings,
    )


def _build_question_analysis(score: ScoreRecord, question: NormalizedQuestion | None) -> QuestionAnalysis:
    score_rate = min(max(score.avg_score / score.full_score, 0), 1)
    knowledge = []
    if question is not None:
        knowledge = [_candidate_to_dict(candidate) for candidate in _select_knowledge_candidates(question)]
    warnings = list(score.warnings)
    if question is None:
        warnings.append("未匹配到规范化题目")
    elif question.needs_review or question.parse_confidence < 0.75:
        warnings.append("P1 解析置信度较低，需要教师复核")

    return QuestionAnalysis(
        question_id=question.question_id if question else None,
        question_no=score.question_no,
        full_score=score.full_score,
        avg_score=score.avg_score,
        score_rate=round(score_rate, 4),
        loss_rate=round(1 - score_rate, 4),
        confirmed_knowledge_points=knowledge,
        severity=_severity(score_rate),
        teacher_review_status="pending",
        stem_text=question.stem_text if question else "",
        stem_markdown=question.stem_markdown if question else "",
        options=[option.model_dump() for option in question.options] if question else [],
        question_type=question.question_type if question else None,
        images=[image.model_dump() for image in question.images] if question else [],
        parse_confidence=question.parse_confidence if question else 0,
        needs_review=bool(question.needs_review) if question else True,
        warnings=warnings,
    )


def _select_knowledge_candidates(question: NormalizedQuestion) -> list[KnowledgeCandidate]:
    if not question.knowledge_candidates:
        return _fallback_knowledge_candidates(question)
    sorted_candidates = sorted(question.knowledge_candidates, key=lambda item: item.confidence, reverse=True)
    selected = [candidate for candidate in sorted_candidates if candidate.confidence >= 0.3]
    return selected[:3] or sorted_candidates[:1]


def _fallback_knowledge_candidates(question: NormalizedQuestion) -> list[KnowledgeCandidate]:
    text = " ".join(
        [
            question.stem_text,
            question.stem_markdown,
            " ".join(option.text for option in question.options),
        ]
    )
    selected: list[KnowledgeCandidate] = []
    seen_codes: set[str] = set()
    for keywords, (code, name) in FALLBACK_KNOWLEDGE_RULES:
        if code in seen_codes:
            continue
        if any(keyword and keyword in text for keyword in keywords):
            selected.append(
                KnowledgeCandidate(
                    code=code,
                    name=name,
                    confidence=0.42,
                    source="heuristic_p2_fallback",
                )
            )
            seen_codes.add(code)
        if len(selected) >= 3:
            break
    return selected


def _build_knowledge_diagnostics(analyses: list[QuestionAnalysis]) -> list[KnowledgeDiagnostic]:
    buckets: dict[str, dict] = {}
    for item in analyses:
        if not item.confirmed_knowledge_points:
            continue
        for kp in item.confirmed_knowledge_points:
            code = kp["code"]
            if code not in buckets:
                buckets[code] = {
                    "name": kp["name"],
                    "full_score": 0.0,
                    "avg_score": 0.0,
                    "question_nos": [],
                }
            buckets[code]["full_score"] += item.full_score
            buckets[code]["avg_score"] += item.avg_score
            buckets[code]["question_nos"].append(item.question_no)

    diagnostics: list[KnowledgeDiagnostic] = []
    for code, bucket in buckets.items():
        score_rate = bucket["avg_score"] / bucket["full_score"] if bucket["full_score"] else 0
        diagnostics.append(
            KnowledgeDiagnostic(
                code=code,
                name=bucket["name"],
                score_rate=round(score_rate, 4),
                loss_rate=round(1 - score_rate, 4),
                severity=_severity(score_rate),
                related_question_nos=bucket["question_nos"],
                suggestion=_suggestion(bucket["name"], score_rate),
            )
        )
    return sorted(diagnostics, key=lambda item: (_severity_rank(item.severity), item.score_rate))


def _build_p3_search_requests(
    diagnostics: list[KnowledgeDiagnostic],
    analyses: list[QuestionAnalysis],
) -> list[P3SearchRequest]:
    question_ids_by_kp: dict[str, list[str]] = {}
    for item in analyses:
        if not item.question_id:
            continue
        for kp in item.confirmed_knowledge_points:
            question_ids_by_kp.setdefault(kp["code"], []).append(item.question_id)

    requests: list[P3SearchRequest] = []
    for item in diagnostics:
        if item.severity == "stable":
            continue
        requests.append(
            P3SearchRequest(
                knowledge_point_codes=[item.code],
                question_type=None,
                difficulty_range=(0.35, 0.75),
                limit=5,
                exclude_question_ids=question_ids_by_kp.get(item.code, []),
            )
        )
    return requests[:8]


def _build_teaching_report(
    paper: NormalizedPaper,
    class_name: str,
    analyses: list[QuestionAnalysis],
    diagnostics: list[KnowledgeDiagnostic],
    knowledge_tag_coverage: float,
) -> TeachingReport:
    priority = [item.question_no for item in sorted(analyses, key=lambda q: q.score_rate)[:6]]
    weak = [item.name for item in diagnostics if item.severity in {"critical", "weak"}][:6]
    avg_rate = sum(item.avg_score for item in analyses) / sum(item.full_score for item in analyses) if analyses else 0

    lines = [
        f"# {paper.source.name} 教师端分析报告",
        "",
        f"班级：{class_name}",
        f"整体得分率：{avg_rate:.1%}",
        f"知识点覆盖率：{knowledge_tag_coverage:.1%}",
        "",
        "## 优先讲评题",
    ]
    for item in sorted(analyses, key=lambda q: q.score_rate)[:6]:
        kp_names = "、".join(kp["name"] for kp in item.confirmed_knowledge_points) or "知识点未标注"
        lines.append(f"- {item.question_no}：得分率 {item.score_rate:.1%}，知识点：{kp_names}")

    lines.extend(["", "## 薄弱知识点"])
    for item in diagnostics[:6]:
        lines.append(f"- {item.name}：得分率 {item.score_rate:.1%}，涉及题号 {', '.join(item.related_question_nos)}。{item.suggestion}")

    return TeachingReport(
        title=f"{paper.source.name} 教师端分析报告",
        summary=f"本次分析匹配 {len(analyses)} 道题，整体得分率 {avg_rate:.1%}，知识点覆盖率 {knowledge_tag_coverage:.1%}。",
        priority_question_nos=priority,
        weak_knowledge_points=weak,
        markdown="\n".join(lines),
    )


def _knowledge_tag_coverage(analyses: list[QuestionAnalysis]) -> float:
    if not analyses:
        return 0
    tagged = sum(1 for item in analyses if item.confirmed_knowledge_points)
    return round(tagged / len(analyses), 4)


def _candidate_to_dict(candidate: KnowledgeCandidate) -> dict:
    return {
        "code": candidate.code,
        "name": candidate.name,
        "confidence": candidate.confidence,
        "source": candidate.source,
    }


def _severity(score_rate: float) -> str:
    if score_rate < 0.45:
        return "critical"
    if score_rate < 0.60:
        return "weak"
    if score_rate < 0.75:
        return "watch"
    return "stable"


def _severity_rank(value: str) -> int:
    return {"critical": 0, "weak": 1, "watch": 2, "stable": 3}.get(value, 4)


def _suggestion(name: str, score_rate: float) -> str:
    if score_rate < 0.45:
        return f"建议在讲评课中重建“{name}”的基本模型，并安排同类基础题回炉。"
    if score_rate < 0.60:
        return f"建议围绕“{name}”安排分层训练，先基础巩固再提升迁移。"
    if score_rate < 0.75:
        return f"建议用 1 到 2 道变式题确认“{name}”是否真正掌握。"
    return f"“{name}”整体较稳定，可作为综合题中的辅助知识点。"


def _normalize_question_no(value: str) -> str:
    return value.strip().replace("（", "(").replace("）", ")").replace(" ", "")
