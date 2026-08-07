import hashlib
import html
import json
import re
from collections import Counter
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from resources.models import KnowledgePoint, QuestionBankItem


CORE_JUNIOR_KNOWLEDGE_POINTS = [
    {
        "knowledge_point_id": "kp_math_junior_number_algebra",
        "code": "MATH.JH.01",
        "name": "数与代数",
        "parent_id": None,
        "path": ["数与代数"],
        "sort_order": 100,
    },
    {
        "knowledge_point_id": "kp_math_junior_equation",
        "code": "MATH.JH.01.01",
        "name": "方程与不等式",
        "parent_id": "kp_math_junior_number_algebra",
        "path": ["数与代数", "方程与不等式"],
        "sort_order": 110,
    },
    {
        "knowledge_point_id": "kp_math_7_linear_equation",
        "code": "MATH.7.EQ.001",
        "name": "一元一次方程",
        "parent_id": "kp_math_junior_equation",
        "path": ["数与代数", "方程与不等式", "一元一次方程"],
        "sort_order": 111,
    },
    {
        "knowledge_point_id": "kp_math_8_function",
        "code": "MATH.8.FUNC",
        "name": "函数",
        "parent_id": "kp_math_junior_number_algebra",
        "path": ["数与代数", "函数"],
        "sort_order": 120,
    },
    {
        "knowledge_point_id": "kp_math_8_function_linear",
        "code": "MATH.8.FUNC.001",
        "name": "一次函数图像与性质",
        "parent_id": "kp_math_8_function",
        "path": ["数与代数", "函数", "一次函数图像与性质"],
        "sort_order": 121,
    },
    {
        "knowledge_point_id": "kp_math_8_function_application",
        "code": "MATH.8.FUNC.002",
        "name": "一次函数实际应用",
        "parent_id": "kp_math_8_function",
        "path": ["数与代数", "函数", "一次函数实际应用"],
        "sort_order": 122,
    },
    {
        "knowledge_point_id": "kp_math_9_quadratic_function",
        "code": "MATH.9.FUNC.001",
        "name": "二次函数图像与性质",
        "parent_id": "kp_math_8_function",
        "path": ["数与代数", "函数", "二次函数图像与性质"],
        "sort_order": 123,
    },
    {
        "knowledge_point_id": "kp_math_9_inverse_function",
        "code": "MATH.9.FUNC.002",
        "name": "反比例函数",
        "parent_id": "kp_math_8_function",
        "path": ["数与代数", "函数", "反比例函数"],
        "sort_order": 124,
    },
    {
        "knowledge_point_id": "kp_math_junior_algebra_ops",
        "code": "MATH.JH.01.02",
        "name": "式与运算",
        "parent_id": "kp_math_junior_number_algebra",
        "path": ["数与代数", "式与运算"],
        "sort_order": 130,
    },
    {
        "knowledge_point_id": "kp_math_junior_geometry",
        "code": "MATH.JH.02",
        "name": "图形与几何",
        "parent_id": None,
        "path": ["图形与几何"],
        "sort_order": 200,
    },
    {
        "knowledge_point_id": "kp_math_8_triangle",
        "code": "MATH.8.GEO.001",
        "name": "三角形全等",
        "parent_id": "kp_math_junior_geometry",
        "path": ["图形与几何", "三角形", "三角形全等"],
        "sort_order": 210,
    },
    {
        "knowledge_point_id": "kp_math_8_triangle_side_relation",
        "code": "MATH.8.GEO.002",
        "name": "三角形三边关系",
        "parent_id": "kp_math_8_triangle",
        "path": ["图形与几何", "三角形", "三角形三边关系"],
        "sort_order": 211,
    },
    {
        "knowledge_point_id": "kp_math_9_circle",
        "code": "MATH.9.GEO.001",
        "name": "圆的基本性质",
        "parent_id": "kp_math_junior_geometry",
        "path": ["图形与几何", "圆"],
        "sort_order": 220,
    },
    {
        "knowledge_point_id": "kp_math_9_similarity",
        "code": "MATH.9.GEO.002",
        "name": "相似三角形",
        "parent_id": "kp_math_junior_geometry",
        "path": ["图形与几何", "相似三角形"],
        "sort_order": 230,
    },
    {
        "knowledge_point_id": "kp_math_8_quadrilateral",
        "code": "MATH.8.GEO.003",
        "name": "四边形性质",
        "parent_id": "kp_math_junior_geometry",
        "path": ["图形与几何", "四边形"],
        "sort_order": 240,
    },
    {
        "knowledge_point_id": "kp_math_9_trigonometry",
        "code": "MATH.9.GEO.004",
        "name": "锐角三角函数",
        "parent_id": "kp_math_junior_geometry",
        "path": ["图形与几何", "锐角三角函数"],
        "sort_order": 250,
    },
    {
        "knowledge_point_id": "kp_math_junior_solid_geometry",
        "code": "MATH.JH.02.01",
        "name": "视图与几何体",
        "parent_id": "kp_math_junior_geometry",
        "path": ["图形与几何", "视图与几何体"],
        "sort_order": 260,
    },
    {
        "knowledge_point_id": "kp_math_junior_statistics",
        "code": "MATH.JH.03",
        "name": "统计",
        "parent_id": None,
        "path": ["统计与概率", "统计"],
        "sort_order": 300,
    },
    {
        "knowledge_point_id": "kp_math_junior_probability",
        "code": "MATH.JH.03.01",
        "name": "概率",
        "parent_id": "kp_math_junior_statistics",
        "path": ["统计与概率", "概率"],
        "sort_order": 310,
    },
]

BROAD_RULES = [
    (("统计", "中位数", "众数", "平均数", "方差", "频率", "样本", "调查", "数据"), "kp_math_junior_statistics"),
    (("概率", "树状图", "列表法", "随机"), "kp_math_junior_probability"),
    (("二次函数", "抛物线"), "kp_math_9_quadratic_function"),
    (("反比例函数",), "kp_math_9_inverse_function"),
    (("一次函数", "正比例函数", "待定系数法"), "kp_math_8_function_linear"),
    (("函数关系", "函数表达式", "函数解析式", "实际应用"), "kp_math_8_function_application"),
    (("函数",), "kp_math_8_function"),
    (("方程", "不等式", "方程组", "根与系数", "韦达"), "kp_math_junior_equation"),
    (("圆", "切线", "圆周角", "弧长", "扇形", "垂径"), "kp_math_9_circle"),
    (("相似",), "kp_math_9_similarity"),
    (("三边关系",), "kp_math_8_triangle_side_relation"),
    (("全等", "三角形", "勾股", "角平分线", "等腰", "直角三角形"), "kp_math_8_triangle"),
    (("平行四边形", "矩形", "正方形", "菱形", "四边形"), "kp_math_8_quadrilateral"),
    (("三角函数", "正弦", "余弦", "正切"), "kp_math_9_trigonometry"),
    (("三视图", "几何体", "立体", "圆锥", "圆柱"), "kp_math_junior_solid_geometry"),
    (("分式", "整式", "因式分解", "平方差", "完全平方", "幂", "同类项", "绝对值", "科学记数法", "二次根式", "实数"), "kp_math_junior_algebra_ops"),
]

QUESTION_TYPE_LABELS = {
    "single_choice": "选择题",
    "multiple_choice": "多选题",
    "blank": "填空题",
    "solution": "解答题",
}

DIFFICULTY_MAP = {
    1: 0.25,
    2: 0.35,
    3: 0.55,
    4: 0.72,
    5: 0.88,
}


class Command(BaseCommand):
    help = "Import normalized P1 paper outputs into the P3 question bank."

    def add_arguments(self, parser):
        parser.add_argument(
            "--source",
            default=None,
            help="Directory containing P1 paper.json outputs. Defaults to campus_p1/web_app/backend/papers.",
        )
        parser.add_argument(
            "--knowledge-version",
            default=KnowledgePoint.DEFAULT_VERSION,
            help="Knowledge point version to attach questions to.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Import only the first N papers. Useful for smoke tests.",
        )
        parser.add_argument(
            "--min-specific-frequency",
            type=int,
            default=3,
            help="Only create fine-grained Qwen knowledge points seen at least this many times.",
        )
        parser.add_argument(
            "--specific-knowledge-limit",
            type=int,
            default=3,
            help="Maximum fine-grained Qwen knowledge points linked to each question.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Validate and summarize without writing to the database.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        source = self._resolve_source(options["source"])
        paper_paths = sorted(source.rglob("paper.json"))
        if options["limit"]:
            paper_paths = paper_paths[: options["limit"]]
        if not paper_paths:
            raise CommandError(f"No paper.json files found under {source}")

        papers = [self._load_paper(path) for path in paper_paths]
        qwen_counter = self._count_qwen_knowledge(papers)
        specific_names = {
            name
            for name, count in qwen_counter.items()
            if count >= options["min_specific_frequency"]
        }

        if options["dry_run"]:
            question_count = sum(len(paper.get("questions", [])) for paper in papers)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Dry run: {len(papers)} papers, {question_count} questions, "
                    f"{len(specific_names)} specific knowledge points."
                )
            )
            return

        version = options["knowledge_version"]
        self._ensure_core_knowledge_points(version)
        specific_stats = self._ensure_specific_knowledge_points(
            specific_names,
            version,
            qwen_counter,
        )

        created_count = 0
        updated_count = 0
        skipped_count = 0
        for paper_path, paper in zip(paper_paths, papers):
            for question in paper.get("questions", []):
                knowledge_point_ids = self._knowledge_point_ids_for_question(
                    question,
                    specific_names,
                    specific_limit=options["specific_knowledge_limit"],
                )
                if not knowledge_point_ids:
                    skipped_count += 1
                    continue
                _, created = self._upsert_question(
                    paper_path=paper_path,
                    paper=paper,
                    question=question,
                    knowledge_point_ids=knowledge_point_ids,
                    version=version,
                )
                if created:
                    created_count += 1
                else:
                    updated_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Imported {created_count + updated_count} P1 questions from {len(papers)} papers: "
                f"{created_count} created, {updated_count} updated, {skipped_count} skipped; "
                f"specific knowledge points {specific_stats['created']} created, "
                f"{specific_stats['updated']} updated."
            )
        )

    def _resolve_source(self, source_option):
        if source_option:
            source = Path(source_option)
            if not source.is_absolute():
                source = Path.cwd() / source
            return source
        return Path(__file__).resolve().parents[5] / "campus_p1" / "web_app" / "backend" / "papers"

    def _load_paper(self, path):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise CommandError(f"Invalid JSON in {path}: {exc}") from exc

    def _count_qwen_knowledge(self, papers):
        counter = Counter()
        for paper in papers:
            for question in paper.get("questions", []):
                counter.update(self._qwen_knowledge_names(question))
        return counter

    def _ensure_core_knowledge_points(self, version):
        for item in CORE_JUNIOR_KNOWLEDGE_POINTS:
            KnowledgePoint.objects.update_or_create(
                knowledge_point_id=item["knowledge_point_id"],
                version=version,
                defaults={
                    "code": item["code"],
                    "name": item["name"],
                    "parent_id": item["parent_id"],
                    "subject": "math",
                    "stage": "junior_middle_school",
                    "grade_range": ["7", "8", "9"],
                    "path": item["path"],
                    "enabled": True,
                    "sort_order": item["sort_order"],
                },
            )

    def _ensure_specific_knowledge_points(self, names, version, frequency):
        existing_ids = set(
            KnowledgePoint.objects.filter(version=version).values_list(
                "knowledge_point_id",
                flat=True,
            )
        )
        created_count = 0
        updated_count = 0
        for index, name in enumerate(sorted(names), start=1):
            point_id = _specific_point_id(name)
            parent_id = self._broad_ids_for_text(name)[0]
            _, created = KnowledgePoint.objects.update_or_create(
                knowledge_point_id=point_id,
                version=version,
                defaults={
                    "code": _specific_point_code(name),
                    "name": name[:120],
                    "parent_id": parent_id,
                    "subject": "math",
                    "stage": "junior_middle_school",
                    "grade_range": ["7", "8", "9"],
                    "path": ["P1 AI 细粒度知识点", name[:120]],
                    "enabled": True,
                    "sort_order": 20000 + index,
                },
            )
            if created and point_id not in existing_ids:
                created_count += 1
            else:
                updated_count += 1
        return {"created": created_count, "updated": updated_count}

    def _knowledge_point_ids_for_question(self, question, specific_names, specific_limit):
        text = self._question_text(question)
        knowledge_point_ids = list(self._broad_ids_for_text(text))
        for name in self._qwen_knowledge_names(question):
            if name not in specific_names:
                continue
            knowledge_point_ids.append(_specific_point_id(name))
            if len([item for item in knowledge_point_ids if item.startswith("kp_math_jh_auto_")]) >= specific_limit:
                break
        return list(dict.fromkeys(knowledge_point_ids)) or ["kp_math_junior_number_algebra"]

    def _broad_ids_for_text(self, text):
        matched = []
        for keywords, point_id in BROAD_RULES:
            if any(keyword in text for keyword in keywords):
                matched.append(point_id)
        return list(dict.fromkeys(matched))[:3] or ["kp_math_junior_number_algebra"]

    def _upsert_question(self, paper_path, paper, question, knowledge_point_ids, version):
        bank_question_id = _bank_question_id(paper.get("paper_id", paper_path.parent.name), question)
        values = {
            "source": QuestionBankItem.Source.MIDDLE_EXAM_REAL,
            "content_html": self._content_html(paper, question),
            "answer_html": _paragraph_html(question.get("answer") or "待补充"),
            "analysis_html": self._analysis_html(question),
            "question_type": QUESTION_TYPE_LABELS.get(
                question.get("question_type"),
                question.get("question_type") or "题目",
            ),
            "difficulty": DIFFICULTY_MAP.get(int(question.get("difficulty") or 3), 0.55),
            "images": self._image_payloads(paper_path, paper, question),
            "audit_status": QuestionBankItem.AuditStatus.APPROVED,
            "knowledge_point_version": version,
        }
        question_obj, created = QuestionBankItem.objects.update_or_create(
            bank_question_id=bank_question_id,
            defaults=values,
        )
        knowledge_points = list(
            KnowledgePoint.objects.filter(
                knowledge_point_id__in=knowledge_point_ids,
                version=version,
            )
        )
        question_obj.knowledge_points.set(knowledge_points)
        return question_obj, created

    def _content_html(self, paper, question):
        lines = [
            f"<p><strong>{html.escape(str(question.get('question_no') or ''))}.</strong> "
            f"{html.escape(question.get('stem_text') or '')}</p>"
        ]
        options = question.get("options") or []
        if options:
            lines.append("<ol type=\"A\">")
            for option in options:
                label = html.escape(str(option.get("label") or ""))
                text = html.escape(str(option.get("text") or ""))
                lines.append(f"<li data-label=\"{label}\">{text}</li>")
            lines.append("</ol>")
        lines.append(f"<p class=\"source-paper\">来源：{html.escape(paper.get('source', {}).get('name') or '')}</p>")
        return "\n".join(lines)

    def _analysis_html(self, question):
        qwen_names = self._qwen_knowledge_names(question)
        lines = []
        if qwen_names:
            lines.append(f"<p>AI 识别知识点：{html.escape('、'.join(qwen_names))}</p>")
        solution = question.get("solution") or "待补充"
        lines.append(_paragraph_html(solution))
        return "\n".join(lines)

    def _image_payloads(self, paper_path, paper, question):
        payloads = []
        paper_dir = paper_path.parent
        root = Path(__file__).resolve().parents[5]
        for image in question.get("images") or []:
            raw_path = image.get("path") or ""
            asset_path = paper_dir / raw_path
            try:
                repo_rel = asset_path.resolve().relative_to(root.resolve()).as_posix()
                asset_url = f"/api/assets/{repo_rel}"
            except ValueError:
                repo_rel = asset_path.as_posix()
                asset_url = ""
            payloads.append(
                {
                    "image_id": image.get("image_id") or "",
                    "role": image.get("role") or "stem",
                    "path": raw_path,
                    "repo_path": repo_rel,
                    "asset_url": asset_url,
                    "paper_id": paper.get("paper_id", ""),
                }
            )
        return payloads

    def _question_text(self, question):
        chunks = [
            question.get("stem_text") or "",
            question.get("stem_markdown") or "",
            " ".join(str(option.get("text") or "") for option in question.get("options") or []),
            " ".join(self._qwen_knowledge_names(question)),
        ]
        return " ".join(chunks)

    def _qwen_knowledge_names(self, question):
        raw_names = (question.get("qwen_analysis") or {}).get("knowledge_points") or []
        names = []
        for name in raw_names:
            normalized = re.sub(r"\s+", "", str(name or ""))
            if normalized:
                names.append(normalized[:120])
        return list(dict.fromkeys(names))


def _specific_point_id(name):
    digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:16]
    return f"kp_math_jh_auto_{digest}"


def _specific_point_code(name):
    digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:12].upper()
    return f"MATH.JH.AUTO.{digest}"


def _bank_question_id(paper_id, question):
    key = f"{paper_id}:{question.get('question_id') or question.get('question_no')}"
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
    return f"bq_p1_{digest}"


def _paragraph_html(text):
    paragraphs = [item.strip() for item in str(text).splitlines() if item.strip()]
    if not paragraphs:
        return "<p>待补充</p>"
    return "\n".join(f"<p>{html.escape(item)}</p>" for item in paragraphs)
