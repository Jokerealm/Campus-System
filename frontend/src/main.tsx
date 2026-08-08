import React from "react";
import ReactDOM from "react-dom/client";
import "./styles.css";

function resolveApiBase() {
  const fromQuery = new URLSearchParams(window.location.search).get("apiBase");
  return fromQuery || import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";
}

const API_BASE = resolveApiBase();
const CLIENT_CONTEXT = {
  tenantId: import.meta.env.VITE_CAMPUS_TENANT_ID || safeLocalStorage("campus_tenant_id") || "campus_school",
  teacherId: import.meta.env.VITE_CAMPUS_TEACHER_ID || safeLocalStorage("campus_teacher_id") || "teacher",
  studentId: import.meta.env.VITE_CAMPUS_STUDENT_ID || safeLocalStorage("campus_student_id") || "student",
  authToken: import.meta.env.VITE_CAMPUS_DEMO_AUTH_TOKEN || safeLocalStorage("campus_demo_auth_token") || "",
};

type Severity = "critical" | "weak" | "watch" | "stable";
type QuestionFilter = Severity | "priority" | "all";
type Stage = "senior_high" | "junior_high";
type TeacherNavSection = "workspace" | "review" | "questions" | "knowledge" | "practice" | "report";

type CalibrationNavState = {
  status: "idle" | "running" | "succeeded" | "failed";
  elapsedSeconds: number;
  message?: string;
};

type KnowledgePointRef = {
  code: string;
  name: string;
  confidence?: number;
  source?: string;
};

type QuestionImageRef = {
  image_id: string;
  path: string;
  role?: string;
};

type QuestionOption = {
  label: string;
  text: string;
};

type QuestionAnalysis = {
  question_id: string | null;
  question_no: string;
  full_score: number;
  avg_score: number;
  score_rate: number;
  loss_rate: number;
  confirmed_knowledge_points: KnowledgePointRef[];
  severity: Severity;
  teacher_review_status: "pending" | "confirmed";
  stem_text: string;
  stem_markdown?: string;
  options?: QuestionOption[];
  question_type: string | null;
  images?: QuestionImageRef[];
  parse_confidence?: number;
  needs_review?: boolean;
  warnings: string[];
};

type KnowledgeDiagnostic = {
  code: string;
  name: string;
  score_rate: number;
  loss_rate: number;
  severity: Severity;
  related_question_nos: string[];
  suggestion: string;
};

type TeachingReport = {
  title: string;
  summary: string;
  priority_question_nos: string[];
  weak_knowledge_points: string[];
  markdown: string;
};

type P3SearchRequest = {
  knowledge_point_codes: string[];
  knowledge_point_ids?: string[];
  question_type: string | null;
  difficulty_range: [number, number];
  limit: number;
  exclude_question_ids: string[];
};

type QuestionRecommendation = {
  bank_question_id: string;
  source: string;
  content_html: string;
  answer_html: string;
  analysis_html: string;
  knowledge_point_ids: string[];
  question_type: string;
  difficulty: number;
  match_score: number;
  recommend_reason: string;
};

type PracticeRecommendationGroup = {
  knowledge_point_code: string;
  knowledge_point_id: string;
  knowledge_point_name: string;
  score_rate?: number;
  loss_rate?: number;
  severity: Severity;
  related_question_nos: string[];
  items: QuestionRecommendation[];
  need_ai_generation: boolean;
  source: string;
};

type PracticePackResult = {
  practice_pack_id: string;
  status: string;
  title: string;
  target: string;
  target_ref_id: string;
  knowledge_point_ids: string[];
  question_ids: string[];
  source: string;
  needs_p3_sync: boolean;
  message: string;
  created_at?: string;
};

type P2ExamAnalysis = {
  exam_id: string;
  paper_id: string;
  class_name: string;
  knowledge_tag_coverage?: number;
  question_analysis: QuestionAnalysis[];
  knowledge_diagnostics: KnowledgeDiagnostic[];
  p3_search_requests: P3SearchRequest[];
  practice_recommendations?: PracticeRecommendationGroup[];
  practice_packs?: PracticePackResult[];
  teaching_report: TeachingReport;
  warnings: string[];
};

type AiKnowledgeTagJob = {
  job_id: string;
  exam_id: string;
  status: "queued" | "running" | "succeeded" | "failed";
  message: string;
  updated_count: number;
  total_count: number;
  error?: string | null;
};

type ExamSummary = {
  exam_id: string;
  status: string;
  name: string;
  grade: string;
  tenant_id?: string;
  question_count: number;
  file_types: string[];
  diagnostic_ids: string[];
  lesson_plan_count: number;
  practice_pack_count: number;
  is_system_test?: boolean;
  latest_lesson_plan?: {
    lesson_plan_id: string;
    diagnostic_id: string;
    file_name: string;
    download_url: string;
    size_bytes: number;
    created_at: string;
  } | null;
  latest_practice_pack?: PracticePackResult | null;
  updated_at: string;
};

type ApiEnvelope<T> = {
  request_id: string;
  code: string;
  message: string;
  data: T;
};

type UploadedFilePayload = {
  file: {
    file_id: string;
    file_name: string;
    mime_type: string;
    size_bytes: number;
  };
};

type QuestionDraft = {
  question_no: string;
  stem_text: string;
  option_text: string;
  question_type: string;
  full_score: string;
  knowledge_text: string;
  image_text: string;
};

type RecommendationDraft = {
  content_text: string;
  answer_text: string;
  analysis_text: string;
  recommend_reason: string;
  question_type: string;
  difficulty: string;
};

type WrongQuestionCandidate = {
  knowledge_point_id: string;
  knowledge_point_name: string;
  confidence: number;
  reason?: string;
};

type WrongQuestionRecognizedQuestion = {
  stem_text: string;
  stem_html: string;
  question_type: string;
  images: unknown[];
  parse_confidence: number;
  needs_review: boolean;
};

type WrongQuestionRecognitionResult = {
  status: string;
  result?: {
    student_id: string;
    question: WrongQuestionRecognizedQuestion;
    knowledge_candidates: WrongQuestionCandidate[];
  } | null;
  error?: string | null;
};

type P1JobStatus = {
  job_id: string;
  job_type: string;
  status: string;
  progress: number;
  result_url?: string | null;
  error?: string | null;
};

type GuidedExplanationResult = {
  step_index: number;
  content: string;
  next_action: string;
  can_show_full_answer: boolean;
};

type GeneratedVariant = {
  generated_question_id: string;
  content_html: string;
  answer_html: string;
  analysis_html: string;
  knowledge_point_ids: string[];
  question_type?: string;
  difficulty: number;
  audit_status: string;
};

type VariantGenerationResult = {
  items: GeneratedVariant[];
  source: string;
};

type StudentFlowState = {
  jobId: string;
  jobStatus: string;
  questionHtml: string;
  questionText: string;
  questionType: string;
  parseConfidence: number;
  candidates: WrongQuestionCandidate[];
  guided: GuidedExplanationResult;
  variants: GeneratedVariant[];
  variantSource: string;
  updatedAt: string;
};

type GeneratedQuestionAuditItem = {
  generated_question_id: string;
  source_question_id?: string | null;
  content_html: string;
  answer_html: string;
  analysis_html: string;
  knowledge_point_ids: string[];
  knowledge_point_version: string;
  question_type: string;
  difficulty: number;
  validation: Record<string, unknown>;
  audit_status: string;
  reviewer_id?: string | null;
  review_comment?: string;
  bank_question_id?: string | null;
  model_name?: string;
  prompt_version?: string;
  created_at?: string;
  updated_at?: string;
};

type GeneratedQuestionAuditList = {
  items: GeneratedQuestionAuditItem[];
  source: string;
};

type GeneratedQuestionReviewResult = {
  generated_question_id: string;
  audit_status: string;
  bank_question_id?: string | null;
  source: string;
  message?: string;
};

type AuditLogItem = {
  id: number;
  event: string;
  resource_type: string;
  resource_id: string;
  payload: Record<string, unknown>;
  created_at: string;
};

type ReadinessComponent = {
  key: string;
  name: string;
  status: string;
  detail: string;
};

type DemoReadiness = {
  overall_status: string;
  components: ReadinessComponent[];
  facts: {
    paper_count: number;
    question_count: number;
    knowledge_point_count: number;
    exam_count: number;
    lesson_plan_count: number;
    practice_pack_count: number;
    system_test_exam_count?: number;
    system_test_lesson_plan_count?: number;
    system_test_practice_pack_count?: number;
  };
  p3: {
    configured: boolean;
    connected: boolean;
    sample_search_count: number;
  };
  llm: {
    enabled: boolean;
    base_url_configured: boolean;
    model: string;
  };
  security?: {
    auth_required: boolean;
    token_configured: boolean;
    default_tenant_id: string;
    file_hashing_enabled: boolean;
    static_assets_scoped: boolean;
    max_paper_upload_mb: number;
    max_score_upload_mb: number;
    detail: string;
  };
};

type AuthSession = {
  actor: {
    actor_id: string;
    actor_role: "teacher" | "student" | "service" | string;
    role_label: string;
    tenant_id: string;
    display_name?: string;
    identity_source?: string;
  };
  auth: {
    auth_required: boolean;
    token_configured: boolean;
    mode: "demo_open" | "identity_headers" | "bearer_token" | string;
    secret_visible: boolean;
    identity_directory_required?: boolean;
  };
  identity_directory?: {
    configured: boolean;
    source: string;
    required: boolean;
    tenant_count: number;
    user_count: number;
    roles: string[];
  };
  permissions: { key: string; label: string }[];
  request_headers: Record<string, string>;
};

type StudentPracticeItem = {
  bank_question_id: string;
  content_html: string;
  answer_html?: string;
  analysis_html?: string;
  knowledge_point_ids: string[];
  knowledge_point_version: string;
  question_type: string;
  difficulty: number;
  images: unknown[];
  recommend_reason: string;
};

type StudentPracticeRecommendationList = {
  student_id: string;
  source: string;
  items: StudentPracticeItem[];
  detail?: string;
};

type StudentMasteryUpdate = {
  knowledge_point_id: string;
  knowledge_point_code?: string;
  knowledge_point_name?: string;
  mastery_rate: number;
};

type StudentPracticeAnswerResult = {
  student_id: string;
  source: string;
  answer_record_id: string;
  updated_mastery: StudentMasteryUpdate[];
  detail?: string;
};

type StudentRecentAnswer = {
  answer_record_id: string;
  bank_question_id: string;
  question_type: string;
  answer_text: string;
  is_correct: boolean;
  used_seconds: number;
  knowledge_point_ids: string[];
  mastery_snapshot: StudentMasteryUpdate[];
  created_at: string;
};

type StudentPracticeHistoryItem = StudentRecentAnswer & {
  content_preview: string;
};

type StudentPracticeHistory = {
  student_id: string;
  source: string;
  total_count: number;
  limit: number;
  offset: number;
  items: StudentPracticeHistoryItem[];
  detail?: string;
};

type StudentPracticeProgress = {
  student_id: string;
  source: string;
  answer_count: number;
  correct_count: number;
  accuracy_rate: number;
  mastery_count: number;
  mastery: StudentMasteryUpdate[];
  recent_answers: StudentRecentAnswer[];
  detail?: string;
};

type StudentPersonalReportAction = {
  action_type: string;
  title: string;
  detail: string;
  priority: string;
  knowledge_point_ids: string[];
};

type StudentPersonalReport = {
  student_id: string;
  source: string;
  generated_at: string;
  summary: {
    answer_count: number;
    correct_count: number;
    accuracy_rate: number;
    wrong_question_count: number;
    active_wrong_question_count: number;
    mastered_wrong_question_count: number;
    mastery_count: number;
    average_mastery_rate: number;
    report_level: string;
  };
  mastery: {
    weak: StudentMasteryUpdate[];
    strong: StudentMasteryUpdate[];
  };
  wrong_question_status: Record<string, number>;
  recent_wrong_questions: Array<{
    wrong_question_id: string;
    status: string;
    question_type?: string;
    stem_preview?: string;
    confirmed_knowledge_point_ids: string[];
    updated_at: string;
  }>;
  recent_answers: StudentRecentAnswer[];
  recommended_question_ids: string[];
  next_actions: StudentPersonalReportAction[];
};

type StudentWrongQuestionCandidate = {
  knowledge_point_id: string;
  knowledge_point_name?: string;
  confidence?: number;
  reason?: string;
};

type StudentWrongQuestionDetail = {
  student_id: string;
  source?: string;
  wrong_question_id: string;
  recognition_job_id?: string;
  recognition_error?: string;
  status: string;
  question: {
    stem_html?: string;
    stem_text?: string;
    question_type?: string;
    parse_confidence?: number;
    needs_review?: boolean;
    images?: unknown[];
  };
  knowledge_candidates: StudentWrongQuestionCandidate[];
  confirmed_knowledge_point_ids: string[];
};

type StudentWrongQuestionUploadResult = {
  student_id: string;
  source: string;
  wrong_question_id: string;
  recognition_job_id?: string;
  status: string;
};

type StudentGuidedExplanation = {
  student_id: string;
  source: string;
  step_index: number;
  content: string;
  next_action: string;
  can_show_full_answer: boolean;
};

const severityText: Record<Severity, string> = {
  critical: "重点讲评",
  weak: "薄弱",
  watch: "观察",
  stable: "稳定",
};

const filters: Array<{ key: QuestionFilter; label: string }> = [
  { key: "priority", label: "重点题目" },
  { key: "all", label: "全部题目" },
  { key: "critical", label: "重点讲评" },
  { key: "weak", label: "薄弱" },
  { key: "watch", label: "观察" },
  { key: "stable", label: "稳定" },
];

function examStatusText(status: string) {
  const text: Record<string, string> = {
    draft: "草稿",
    parsing: "解析中",
    teacher_review: "待核对",
    diagnosed: "已诊断",
    lesson_generated: "已生成教案",
    needs_p1: "需处理",
    archived: "已归档",
  };
  return text[status] || status;
}

function fileTypesText(fileTypes: string[]) {
  const text: Record<string, string> = {
    paper: "试卷",
    score_excel: "成绩表",
    analysis: "分析结果",
  };
  return fileTypes.map((item) => text[item] || item).join(" / ");
}

function escapeHtml(value: string) {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function stemTextToHtml(value: string) {
  return `<p>${escapeHtml(value).replace(/\n/g, "<br/>")}</p>`;
}

function questionDisplayText(question: Pick<QuestionAnalysis, "stem_text" | "stem_markdown">) {
  return (question.stem_markdown || "").trim() || question.stem_text || "";
}

function stripInlineImageMarkers(value: string) {
  return value
    .replace(/\s*\[(?:图|图片)\s*[0-9一二三四五六七八九十]+\]\s*/g, " ")
    .replace(/\s{2,}/g, " ");
}

function isStandaloneImageMarker(line: string) {
  return /^(?:\s*\[(?:图|图片)\s*[0-9一二三四五六七八九十]+\]\s*)+$/.test(line);
}

function isMarkdownImageLine(line: string) {
  return /^!\[([^\]]*)\]\(([^)]+)\)$/.test(line.trim());
}

function normalizeQuestionTextForSave(value: string, images: QuestionImageRef[]) {
  if (!images.some((image) => image.path)) return value.trim();
  return value
    .replace(/\r\n/g, "\n")
    .split("\n")
    .map((line) => stripInlineImageMarkers(line).trimEnd())
    .filter((line) => line.trim() && !isMarkdownImageLine(line))
    .join("\n")
    .trim();
}

function isOptionImageRole(role = "", label = "") {
  const normalized = role.toLowerCase().replace(/[\s:-]+/g, "_");
  if (!label) return normalized.startsWith("option_");
  return normalized === `option_${label.toLowerCase()}` || normalized.endsWith(`_${label.toLowerCase()}`);
}

function stemImages(images: QuestionImageRef[]) {
  return images.filter((image) => !isOptionImageRole(image.role || ""));
}

function optionImages(images: QuestionImageRef[], label: string) {
  return images.filter((image) => isOptionImageRole(image.role || "", label));
}

function isMarkdownTableSeparator(line: string) {
  return /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(line.trim());
}

function splitMarkdownTableRow(line: string) {
  let text = line.trim();
  if (text.startsWith("|")) text = text.slice(1);
  if (text.endsWith("|")) text = text.slice(0, -1);
  return text.split("|").map((cell) => cell.trim());
}

function isLikelyMarkdownTable(block: string[]) {
  const rows = block.map((line) => line.trim()).filter(Boolean);
  if (rows.length < 2) return false;
  const splitRows = rows.filter((line) => !isMarkdownTableSeparator(line)).map(splitMarkdownTableRow);
  if (!splitRows.length) return false;
  const hasSeparator = rows.some(isMarkdownTableSeparator);
  const enoughColumns = splitRows.filter((row) => row.length >= 3).length >= 2;
  return hasSeparator || enoughColumns;
}

function renderMathCases(body: string) {
  const rows = body
    .split(/\\\\+/)
    .map((row) => row.replace(/^\s*\$|\$\s*$/g, "").trim())
    .filter(Boolean);
  if (!rows.length) return "";
  return `<span class="math-cases" aria-label="方程组或不等式组"><span class="math-cases-brace">{</span><span class="math-cases-rows">${rows
    .map((row) => `<span>${renderInlineMath(row)}</span>`)
    .join("")}</span></span>`;
}

function replaceMathCases(value: string) {
  const renderedCases: string[] = [];
  const stash = (_match: string, body: string) => {
    const token = `MATHCASEPLACEHOLDER${renderedCases.length}END`;
    renderedCases.push(renderMathCases(body));
    return token;
  };
  const text = value
    .replace(/\$?\\left\\\{\s*\\begin\{array\}\{[lcr]+\}([\s\S]*?)\\end\{array\}\s*\\right\.?\$?/g, stash)
    .replace(/\$?\\left\\\{\s*\\begin\{cases\}([\s\S]*?)\\end\{cases\}\s*\\right\.?\$?/g, stash)
    .replace(/\$?\\begin\{cases\}([\s\S]*?)\\end\{cases\}\$?/g, stash);
  return { text, renderedCases };
}

function renderInlineMath(value: string) {
  const { text, renderedCases } = replaceMathCases(value);
  let htmlText = escapeHtml(text)
    .replace(/\\times/g, "×")
    .replace(/\\cdot/g, "·")
    .replace(/\\leq/g, "≤")
    .replace(/\\geq/g, "≥")
    .replace(/\\neq/g, "≠")
    .replace(/\\angle/g, "∠")
    .replace(/\\triangle/g, "△")
    .replace(/\\pi/g, "π")
    .replace(/\\sqrt\{([^{}]+)\}/g, "√$1")
    .replace(/\\overline\{([^{}]+)\}/g, '<span class="math-overline">$1</span>')
    .replace(/\\bar\{([^{}]+)\}/g, '<span class="math-overline">$1</span>')
    .replace(/\\vec\{([^{}]+)\}/g, '<span class="math-vector">$1</span>');

  htmlText = htmlText.replace(
    /\\frac\{([^{}]+)\}\{([^{}]+)\}/g,
    (_match, numerator: string, denominator: string) =>
      `<span class="math-frac"><span>${numerator}</span><span>${denominator}</span></span>`,
  );
  htmlText = htmlText
    .replace(/\^\{([^{}]+)\}/g, "<sup>$1</sup>")
    .replace(/_\{([^{}]+)\}/g, "<sub>$1</sub>")
    .replace(/\^([0-9A-Za-z+\-]+)/g, "<sup>$1</sup>")
    .replace(/_([0-9A-Za-z+\-]+)/g, "<sub>$1</sub>")
    .replace(/_{3,}/g, '<span class="math-blank" aria-label="填空"></span>')
    .replace(/\$/g, "");
  renderedCases.forEach((caseHtml, index) => {
    htmlText = htmlText.replace(`MATHCASEPLACEHOLDER${index}END`, caseHtml);
  });

  return htmlText;
}

function renderMarkdownTable(block: string[]) {
  const rows = block.filter((line) => !isMarkdownTableSeparator(line)).map(splitMarkdownTableRow);
  const columnCount = Math.max(...rows.map((row) => row.length), 0);
  if (!columnCount) return "";
  const normalizedRows = rows.map((row) => [...row, ...Array(Math.max(0, columnCount - row.length)).fill("")]);
  const [header, ...bodyRows] = normalizedRows;
  const head = `<thead><tr>${header.map((cell) => `<th>${renderInlineMath(cell)}</th>`).join("")}</tr></thead>`;
  const body = `<tbody>${bodyRows
    .map((row) => `<tr>${row.map((cell) => `<td>${renderInlineMath(cell)}</td>`).join("")}</tr>`)
    .join("")}</tbody>`;
  return `<div class="render-table-wrap"><table>${head}${body}</table></div>`;
}

function renderQuestionImages(images: QuestionImageRef[], renderedPaths: Set<string> = new Set()) {
  const safeImages = images.filter((image) => image.path && !renderedPaths.has(questionImageUrl(image.path)));
  if (!safeImages.length) return "";
  return `<div class="render-image-grid">${safeImages
    .map((image) => {
      const src = escapeHtml(questionImageUrl(image.path));
      const caption = escapeHtml(image.role || image.image_id || "题图");
      return `<figure><img src="${src}" alt="${caption}" /><figcaption>${caption}</figcaption></figure>`;
    })
    .join("")}</div>`;
}

function renderQuestionContent(value: string, images: QuestionImageRef[] = []) {
  const hasStructuredImages = images.some((image) => image.path);
  const renderedImagePaths = new Set<string>();
  const lines = (value || "").replace(/\r\n/g, "\n").split("\n");
  const parts: string[] = [];
  for (let index = 0; index < lines.length; index += 1) {
    const line = hasStructuredImages ? stripInlineImageMarkers(lines[index]) : lines[index];
    const trimmed = line.trim();
    if (hasStructuredImages && (isStandaloneImageMarker(trimmed) || isMarkdownImageLine(trimmed))) {
      continue;
    }
    if (!trimmed) {
      parts.push('<div class="render-gap" aria-hidden="true"></div>');
      continue;
    }

    if (trimmed.includes("|")) {
      const block: string[] = [];
      let cursor = index;
      while (cursor < lines.length && lines[cursor].trim() && lines[cursor].includes("|")) {
        block.push(lines[cursor]);
        cursor += 1;
      }
      if (isLikelyMarkdownTable(block)) {
        parts.push(renderMarkdownTable(block));
        index = cursor - 1;
        continue;
      }
    }

    const imageMatch = trimmed.match(/^!\[([^\]]*)\]\(([^)]+)\)$/);
    if (imageMatch) {
      const src = escapeHtml(questionImageUrl(imageMatch[2]));
      renderedImagePaths.add(questionImageUrl(imageMatch[2]));
      const caption = escapeHtml(imageMatch[1] || "题图");
      parts.push(`<figure class="render-inline-image"><img src="${src}" alt="${caption}" /><figcaption>${caption}</figcaption></figure>`);
      continue;
    }

    parts.push(`<p>${renderInlineMath(trimmed)}</p>`);
  }
  return `${parts.join("")}${renderQuestionImages(images, renderedImagePaths)}` || '<p class="muted-text">待补充题干</p>';
}

function QuestionStemRenderer({
  text,
  images = [],
  compact = false,
  onClick,
}: {
  text: string;
  images?: QuestionImageRef[];
  compact?: boolean;
  onClick?: () => void;
}) {
  const rendered = React.useMemo(() => renderQuestionContent(text, images), [text, images]);
  const interactiveProps = onClick
    ? {
        role: "button",
        tabIndex: 0,
        onClick,
        onKeyDown: (event: React.KeyboardEvent<HTMLDivElement>) => {
          if (event.key === "Enter" || event.key === " ") onClick();
        },
      }
    : {};
  return (
    <div
      className={`question-rendered${compact ? " compact" : ""}${onClick ? " editable" : ""}`}
      dangerouslySetInnerHTML={{ __html: rendered }}
      {...interactiveProps}
    />
  );
}

function QuestionOptionsRenderer({
  options = [],
  images = [],
  compact = false,
  onClick,
}: {
  options?: QuestionOption[];
  images?: QuestionImageRef[];
  compact?: boolean;
  onClick?: () => void;
}) {
  const safeOptions = options.filter((option) => option.label || option.text);
  if (!safeOptions.length) return null;

  const interactiveProps = onClick
    ? {
        role: "button",
        tabIndex: 0,
        onClick,
        onKeyDown: (event: React.KeyboardEvent<HTMLDivElement>) => {
          if (event.key === "Enter" || event.key === " ") onClick();
        },
      }
    : {};

  return (
    <div className={`question-options${compact ? " compact" : ""}${onClick ? " editable" : ""}`} {...interactiveProps}>
      {safeOptions.map((option) => (
        <div key={option.label || option.text} className="question-option">
          <span className="question-option-label">{option.label || "-"}</span>
          <QuestionStemRenderer text={option.text || ""} images={optionImages(images, option.label)} compact={compact} />
        </div>
      ))}
    </div>
  );
}

function htmlPreview(value: string, maxLength = 56) {
  const text = value
    .replace(/<br\s*\/?>/gi, " ")
    .replace(/<\/p>/gi, " ")
    .replace(/<[^>]+>/g, "")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&amp;/g, "&")
    .replace(/&nbsp;/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  return text.length > maxLength ? `${text.slice(0, maxLength)}...` : text;
}

function htmlToEditableText(value: string) {
  return value
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<\/p>/gi, "\n")
    .replace(/<[^>]+>/g, "")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&amp;/g, "&")
    .replace(/&nbsp;/g, " ")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function editableTextToHtml(value: string) {
  const trimmed = value.trim();
  if (!trimmed) return "";
  return stemTextToHtml(trimmed);
}

function pct(value: number) {
  return `${Math.round(value * 1000) / 10}%`;
}

function formatDuration(seconds: number) {
  const safe = Math.max(0, Math.floor(seconds));
  const minutes = Math.floor(safe / 60);
  const rest = safe % 60;
  return `${minutes}:${String(rest).padStart(2, "0")}`;
}

function difficultyLabel(value: number) {
  if (value < 0.42) return "基础";
  if (value < 0.68) return "巩固";
  return "提升";
}

function studentReportLevelText(level: string) {
  const text: Record<string, string> = {
    new: "新建画像",
    needs_attention: "需要关注",
    progressing: "稳步推进",
    solid: "状态稳定",
    offline: "离线兜底",
  };
  return text[level] || level;
}

function studentActionText(actionType: string) {
  const text: Record<string, string> = {
    continue_wrong_questions: "先处理未完成错题",
    practice_weak_mastery: "强化薄弱知识点",
    start_first_practice: "完成首道推荐题",
    slow_review: "放慢节奏复盘解析",
    continue_recommendations: "继续推荐练习",
    connect_p3: "连接学生数据服务",
  };
  return text[actionType] || actionType;
}

function wrongStatusText(status: string) {
  const text: Record<string, string> = {
    uploaded: "已上传",
    recognizing: "识别中",
    recognition_failed: "识别失败",
    recognized: "待核对",
    confirmed: "已确认",
    learning: "学习中",
    mastered: "已掌握",
  };
  return text[status] || status;
}

function formatScore(value: number) {
  return Number.isInteger(value) ? `${value}` : value.toFixed(1);
}

function knowledgeNames(points: KnowledgePointRef[], fallback = "知识点未标注") {
  return points.map((item) => item.name).join("、") || fallback;
}

function questionTypeText(type: string | null | undefined) {
  const text: Record<string, string> = {
    single_choice: "单选题",
    multiple_choice: "多选题",
    blank: "填空题",
    solution: "解答题",
  };
  return type ? text[type] || type : "题型未设置";
}

function readinessText(status: string) {
  const text: Record<string, string> = {
    ready: "就绪",
    degraded: "降级",
    fallback: "兜底",
    not_configured: "未配置",
    offline: "离线",
  };
  return text[status] || status;
}

function readinessTone(status?: string) {
  if (status === "ready") return "ready";
  if (status === "fallback" || status === "degraded") return "fallback";
  if (status === "not_configured") return "warning";
  return "offline";
}

function releaseHeadline(readiness: DemoReadiness | null) {
  if (!readiness) return "正在读取服务状态";
  if (readiness.overall_status === "ready") return "服务状态正常";
  if (readiness.overall_status === "fallback" || readiness.overall_status === "degraded") {
    return "核心功能可用";
  }
  if (readiness.overall_status === "not_configured") return "配置待完善";
  return "服务待连接";
}

function ReleaseStrip({ readiness }: { readiness: DemoReadiness | null }) {
  const facts = readiness?.facts;
  const p3Ready = Boolean(readiness?.p3.connected);
  const llmReady = Boolean(readiness?.llm.enabled);
  const securityReady = Boolean(readiness?.security?.file_hashing_enabled && readiness.security.static_assets_scoped);
  const dataReady = Boolean((facts?.paper_count ?? 0) >= 50 && (facts?.knowledge_point_count ?? 0) > 0);

  const items = [
    {
      key: "data",
      tone: dataReady ? "ready" : "warning",
      label: "数据",
      value: facts ? `${facts.paper_count} 套卷 · ${facts.question_count} 题` : "读取中",
      detail: facts ? `${facts.knowledge_point_count} 个知识点已纳入诊断` : "等待服务返回",
    },
    {
      key: "p3",
      tone: p3Ready ? "ready" : "warning",
      label: "题库",
      value: p3Ready ? "已连通" : "待连通",
      detail: p3Ready ? `${readiness?.p3.sample_search_count ?? 0} 条样例检索可用` : "使用本地分析能力",
    },
    {
      key: "llm",
      tone: llmReady ? "ready" : "fallback",
      label: "模型",
      value: llmReady ? "已接入" : "规则兜底",
      detail: llmReady ? readiness?.llm.model || "在线模型可用" : "未配置时使用规则辅助",
    },
    {
      key: "security",
      tone: securityReady ? "ready" : "warning",
      label: "安全",
      value: securityReady ? "已启用" : "待核验",
      detail: readiness?.security?.detail || "文件哈希与静态资源隔离",
    },
  ];

  return (
    <section className={`release-strip ${readinessTone(readiness?.overall_status)}`} aria-label="服务状态">
      <div className="release-strip-main">
        <span>服务状态</span>
        <strong>{releaseHeadline(readiness)}</strong>
        <em>{readiness ? "数据、题库、模型和安全状态" : "正在连接本地后端"}</em>
      </div>
      {items.map((item) => (
        <div key={item.key} className={`release-pill ${item.tone}`}>
          <span>{item.label}</span>
          <strong>{item.value}</strong>
          <em>{item.detail}</em>
        </div>
      ))}
    </section>
  );
}

function appUrl(mode: "teacher" | "student" | "admin", hash = "") {
  const params = new URLSearchParams(window.location.search);
  params.set("apiBase", API_BASE);
  params.delete("t");
  if (mode === "student") params.set("view", "student");
  else if (mode === "admin") params.set("view", "admin");
  else params.delete("view");
  const query = params.toString();
  return `/?${query}${hash}`;
}

function ProductNav({
  mode,
  readiness,
  studentId,
  activeSection = "workspace",
  calibration,
}: {
  mode: "teacher" | "student" | "admin";
  readiness?: DemoReadiness | null;
  studentId?: string;
  activeSection?: TeacherNavSection;
  calibration?: CalibrationNavState;
}) {
  const [session, setSession] = React.useState<AuthSession | null>(null);
  const [sessionError, setSessionError] = React.useState("");
  const teacherMode = mode === "teacher";
  const facts = readiness?.facts;
  const catalogText =
    teacherMode
      ? "Word 试卷"
      : facts?.question_count && facts?.knowledge_point_count
        ? `${facts.question_count} 题 · ${facts.knowledge_point_count} 知识点`
        : "服务检查中";
  const authLabel = session?.auth.auth_required ? "已受保护" : teacherMode ? "教师端" : "本地模式";
  const statusText = sessionError
    ? "需检查"
    : teacherMode
      ? "准备就绪"
      : readiness?.overall_status === "ready"
        ? "服务正常"
        : readiness
          ? "部分能力可用"
          : "连接中";
  const sessionText = mode === "student" ? "学生练习" : mode === "admin" ? "管理后台" : "教师端";
  const statusTitle = session
    ? teacherMode
      ? "上传 Word 试卷与成绩表，生成班级讲评材料"
      : `${sessionText}；${authLabel}；账号源：${session.actor.identity_source || "headers"}；权限：${session.permissions.map((item) => item.label).join("、") || "待配置"}`
    : sessionError || catalogText;

  React.useEffect(() => {
    let cancelled = false;
    const headers = mode === "student" ? studentHeaders(studentId || CLIENT_CONTEXT.studentId) : campusHeaders();
    fetch(`${API_BASE}/auth/session`, { headers })
      .then(async (response) => {
        if (!response.ok) throw new Error(response.statusText || "session failed");
        const payload = (await response.json()) as ApiEnvelope<AuthSession>;
        if (!cancelled) {
          setSession(payload.data);
          setSessionError("");
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setSession(null);
          setSessionError(err instanceof Error ? err.message : "会话不可用");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [mode, studentId]);

  const teacherTabs: Array<{ key: TeacherNavSection; href: string; label: string }> = [
    { key: "workspace", href: "#workspace", label: "导入" },
    { key: "review", href: "#review", label: "核对" },
    { key: "questions", href: "#questions", label: "诊断" },
    { key: "knowledge", href: "#knowledge", label: "知识点" },
    { key: "practice", href: "#practice", label: "推荐" },
    { key: "report", href: "#report", label: "报告" },
  ];
  const calibrationLabel =
    calibration?.status === "running"
      ? `矫正中 ${formatDuration(calibration.elapsedSeconds)}`
      : calibration?.status === "succeeded"
        ? `已矫正 ${formatDuration(calibration.elapsedSeconds)}`
        : calibration?.status === "failed"
          ? "矫正异常"
          : "可智能矫正";

  return (
    <div className={teacherMode ? "product-nav customer-nav" : "product-nav"} aria-label={teacherMode ? "教师端导航" : "系统导航"}>
      {teacherMode ? (
        <a className="product-mark brand-logo" href="#workspace" aria-label="回到首页">
          <img src="/images/campus-brand-logo-clean.png" alt="Campus 智能讲评" />
        </a>
      ) : (
        <a className="product-mark" href={appUrl("teacher")}>
          <span className="product-mark-dot" aria-hidden="true" />
          <span>
            <strong>校园智能学情系统</strong>
            <em>考试分析与精准练习</em>
          </span>
        </a>
      )}
      <nav className="product-tabs" aria-label={teacherMode ? "教师工作台" : "角色与工作区"}>
        {teacherMode ? (
          <>
            {teacherTabs.map((item) => (
              <a
                key={item.key}
                className={activeSection === item.key ? "active" : ""}
                aria-current={activeSection === item.key ? "page" : undefined}
                href={item.href}
              >
                <span className="nav-dot" aria-hidden="true" />
                {item.label}
              </a>
            ))}
          </>
        ) : (
          <a href={appUrl("teacher", "#workspace")}>
            <span className="nav-dot" aria-hidden="true" />
            教师分析
          </a>
        )}
        {!teacherMode && (mode === "student" || mode === "admin") ? (
          <a className={mode === "student" ? "active" : ""} aria-current={mode === "student" ? "page" : undefined} href={appUrl("student")}>
            <span className="nav-dot" aria-hidden="true" />
            学生练习
          </a>
        ) : null}
        {mode === "admin" ? (
          <a className="active" aria-current="page" href={appUrl("admin", "#audit")}>
            <span className="nav-dot" aria-hidden="true" />
            管理后台
          </a>
        ) : null}
      </nav>
      {teacherMode ? (
        <div className="nav-right">
          <span
            className={`calibration-chip ${calibration?.status || "idle"}`}
            title={calibration?.message || "可对知识点进行智能矫正"}
          >
            {calibrationLabel}
          </span>
          <a className="nav-cta" href="#workspace">
            <span className="nav-cta-dot" aria-hidden="true" />
            开始分析
          </a>
          <ThemeToggle />
        </div>
      ) : (
        <div className={sessionError ? "product-status error" : "product-status"} title={statusTitle}>
          <span className="status-dot" aria-hidden="true" />
          <span>{statusText}</span>
          <strong>{sessionText}</strong>
          <em>{catalogText}</em>
          <ThemeToggle />
        </div>
      )}
    </div>
  );
}

function FluidCursor() {
  const auraRef = React.useRef<HTMLDivElement | null>(null);

  React.useEffect(() => {
    const aura = auraRef.current;
    if (!aura) return;
    const auraElement = aura;

    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
    const coarsePointer = window.matchMedia("(pointer: coarse)");
    if (reduceMotion.matches || coarsePointer.matches) return;

    const pointer = {
      x: window.innerWidth * 0.58,
      y: window.innerHeight * 0.28,
      tx: window.innerWidth * 0.58,
      ty: window.innerHeight * 0.28,
      active: false,
    };
    let visible = false;
    let animationId = 0;

    function onPointerMove(event: PointerEvent) {
      pointer.tx = event.clientX;
      pointer.ty = event.clientY;
      pointer.active = true;
      visible = true;
      auraElement.style.opacity = "1";
    }

    function onPointerLeave() {
      visible = false;
      auraElement.style.opacity = "0";
    }

    function onPointerDown() {
      auraElement.classList.add("is-pressed");
    }

    function onPointerUp() {
      auraElement.classList.remove("is-pressed");
      auraElement.classList.add("is-clicked");
      window.setTimeout(() => auraElement.classList.remove("is-clicked"), 360);
    }

    function animate() {
      pointer.x += (pointer.tx - pointer.x) * 0.18;
      pointer.y += (pointer.ty - pointer.y) * 0.18;
      auraElement.style.transform = `translate3d(${pointer.x}px, ${pointer.y}px, 0) translate(-50%, -50%)`;
      if (!visible && pointer.active) auraElement.style.opacity = "0";
      animationId = window.requestAnimationFrame(animate);
    }

    window.addEventListener("pointermove", onPointerMove, { passive: true });
    window.addEventListener("pointerdown", onPointerDown, { passive: true });
    window.addEventListener("pointerup", onPointerUp, { passive: true });
    document.addEventListener("pointerleave", onPointerLeave);
    animationId = window.requestAnimationFrame(animate);

    return () => {
      window.cancelAnimationFrame(animationId);
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerdown", onPointerDown);
      window.removeEventListener("pointerup", onPointerUp);
      document.removeEventListener("pointerleave", onPointerLeave);
    };
  }, []);

  return (
    <div className="cursor-aura" ref={auraRef} aria-hidden="true">
      <span />
    </div>
  );
}

function auditEventText(event: string) {
  const text: Record<string, string> = {
    exam_created: "创建考试",
    exam_file_uploaded: "上传文件",
    exam_parse_started: "开始解析",
    exam_parse_succeeded: "解析完成",
    exam_parse_failed: "解析异常",
    question_structure_updated: "修正题目",
    knowledge_tags_confirmed: "确认知识点",
    diagnostic_run: "生成诊断",
    diagnostic_saved: "保存诊断",
    practice_pack_created: "生成训练包",
    ai_generated_questions_submitted: "AI 题送审",
    ai_generated_question_reviewed: "AI 题审核",
    lesson_plan_generated: "生成教案",
    lesson_plan_downloaded: "下载教案",
    file_saved: "保存文件",
    exam_saved: "保存考试",
  };
  return text[event] || event;
}

function auditResourceText(type: string) {
  const text: Record<string, string> = {
    exam: "考试",
    file: "文件",
    diagnostic: "诊断",
    practice_pack: "训练包",
    generated_question: "AI 题",
    exam_question: "试题",
    lesson_plan: "教案",
  };
  return text[type] || type;
}

function formatAuditTime(value: string) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function makeExamId() {
  const now = new Date();
  const year = now.getFullYear();
  const month = `${now.getMonth() + 1}`.padStart(2, "0");
  const date = `${now.getDate()}`.padStart(2, "0");
  const day = `${year}${month}${date}`;
  return `exam_${day}`;
}

function overallRate(analysis: P2ExamAnalysis | null) {
  if (!analysis) return 0;
  const totalFull = analysis.question_analysis.reduce((sum, item) => sum + item.full_score, 0);
  const totalAvg = analysis.question_analysis.reduce((sum, item) => sum + item.avg_score, 0);
  return totalFull ? totalAvg / totalFull : 0;
}

function countBySeverity(analysis: P2ExamAnalysis | null, severity: Severity) {
  return analysis?.question_analysis.filter((item) => item.severity === severity).length ?? 0;
}

function countRecommendations(analysis: P2ExamAnalysis | null) {
  return analysis?.practice_recommendations?.reduce((sum, group) => sum + group.items.length, 0) ?? 0;
}

function knowledgeCoverage(analysis: P2ExamAnalysis | null) {
  if (!analysis?.question_analysis.length) return 0;
  const tagged = analysis.question_analysis.filter((item) => item.confirmed_knowledge_points.length > 0).length;
  const computed = tagged / analysis.question_analysis.length;
  if (Number.isFinite(analysis.knowledge_tag_coverage) && (analysis.knowledge_tag_coverage ?? 0) > 0) {
    return analysis.knowledge_tag_coverage ?? computed;
  }
  return computed;
}

function severityFromRate(scoreRate: number): Severity {
  if (scoreRate < 0.45) return "critical";
  if (scoreRate < 0.6) return "weak";
  if (scoreRate < 0.75) return "watch";
  return "stable";
}

function suggestionFor(name: string, scoreRate: number) {
  if (scoreRate < 0.45) return `建议在讲评课中重建“${name}”的基本模型，并安排同类基础题回炉。`;
  if (scoreRate < 0.6) return `建议围绕“${name}”安排分层训练，先基础巩固再提升迁移。`;
  if (scoreRate < 0.75) return `建议用 1 到 2 道变式题确认“${name}”是否真正掌握。`;
  return `“${name}”整体较稳定，可作为综合题中的辅助知识点。`;
}

function draftFromQuestion(question: QuestionAnalysis): QuestionDraft {
  return {
    question_no: question.question_no,
    stem_text: questionDisplayText(question),
    option_text: serializeQuestionOptions(question.options || []),
    question_type: question.question_type || "",
    full_score: `${question.full_score}`,
    knowledge_text: question.confirmed_knowledge_points
      .map((item) => `${item.code} | ${item.name}`)
      .join("\n"),
    image_text: serializeQuestionImages(question.images || []),
  };
}

function recommendationKey(group: PracticeRecommendationGroup, item: QuestionRecommendation) {
  return `${group.knowledge_point_code || group.knowledge_point_id}:${item.bank_question_id}`;
}

function recommendationMatchLabel(group: PracticeRecommendationGroup, item: QuestionRecommendation) {
  const ids = item.knowledge_point_ids || [];
  if (group.knowledge_point_id && ids.includes(group.knowledge_point_id)) return "精准匹配";
  if (group.knowledge_point_code && ids.includes(group.knowledge_point_code)) return "精准匹配";
  if (item.match_score >= 0.7) return "相近题";
  return "待核验";
}

function draftFromRecommendation(item: QuestionRecommendation): RecommendationDraft {
  return {
    content_text: htmlToEditableText(item.content_html),
    answer_text: htmlToEditableText(item.answer_html),
    analysis_text: htmlToEditableText(item.analysis_html),
    recommend_reason: item.recommend_reason || "",
    question_type: item.question_type || "",
    difficulty: `${item.difficulty ?? 0.55}`,
  };
}

function serializeQuestionOptions(options: QuestionOption[]) {
  return options.map((item) => `${item.label || ""} | ${item.text || ""}`).join("\n");
}

function parseQuestionOptions(value: string): QuestionOption[] {
  return value
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line, index) => {
      const pipeParts = line.split("|");
      if (pipeParts.length >= 2) {
        return {
          label: pipeParts[0].trim() || String.fromCharCode(65 + index),
          text: pipeParts.slice(1).join("|").trim(),
        };
      }
      const matched = line.match(/^([A-H])[\.\．、\)]?\s*(.*)$/i);
      if (matched) {
        return {
          label: matched[1].toUpperCase(),
          text: matched[2].trim(),
        };
      }
      return {
        label: String.fromCharCode(65 + index),
        text: line,
      };
    })
    .filter((item) => item.label || item.text);
}

function normalizeOptionsForSave(options: QuestionOption[], images: QuestionImageRef[]) {
  return options
    .map((option) => ({
      label: option.label.trim(),
      text: normalizeQuestionTextForSave(option.text, optionImages(images, option.label)) || option.text.trim(),
    }))
    .filter((option) => option.label || option.text);
}

function serializeQuestionImages(images: QuestionImageRef[]) {
  return images.map((item) => `${item.image_id || ""} | ${item.path || ""} | ${item.role || "stem"}`).join("\n");
}

function parseQuestionImages(value: string): QuestionImageRef[] {
  return value
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line, index) => {
      const parts = line.split("|").map((part) => part.trim());
      if (parts.length === 1) {
        return {
          image_id: `img_${index + 1}`,
          path: parts[0],
          role: "stem",
        };
      }
      return {
        image_id: parts[0] || `img_${index + 1}`,
        path: parts[1] || "",
        role: parts[2] || "stem",
      };
    })
    .filter((item) => item.path);
}

function questionImageUrl(path: string) {
  if (!path) return "";
  if (/^https?:\/\//.test(path)) return path;
  if (path.startsWith("/")) return `${API_BASE}${path}`;
  return path;
}

function normalizeQuestionNoForSort(value: string) {
  const circled: Record<string, string> = {
    "①": "1",
    "②": "2",
    "③": "3",
    "④": "4",
    "⑤": "5",
    "⑥": "6",
    "⑦": "7",
    "⑧": "8",
    "⑨": "9",
    "⑩": "10",
    "⑪": "11",
    "⑫": "12",
    "⑬": "13",
    "⑭": "14",
    "⑮": "15",
    "⑯": "16",
    "⑰": "17",
    "⑱": "18",
    "⑲": "19",
    "⑳": "20",
  };
  return value.replace(/[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳]/g, (char) => circled[char] || char);
}

function sortQuestionsForTeacher(questions: QuestionAnalysis[]) {
  return questions
    .slice()
    .sort((left, right) =>
      normalizeQuestionNoForSort(left.question_no).localeCompare(normalizeQuestionNoForSort(right.question_no), "zh-Hans-CN", {
        numeric: true,
      }),
    );
}

function parseKnowledgePoints(value: string): KnowledgePointRef[] {
  return value
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line, index) => {
      const parts = line.split("|").map((part) => part.trim());
      const code = parts[0] || `KP-TEACHER-${index + 1}`;
      const name = parts[1] || parts[0] || `教师确认知识点 ${index + 1}`;
      return {
        code,
        name,
        confidence: 1,
        source: "teacher",
      };
    });
}

function rebuildAnalysis(analysis: P2ExamAnalysis): P2ExamAnalysis {
  const normalizedQuestions = analysis.question_analysis.map((item) => {
    const scoreRate = item.full_score > 0 ? Math.min(Math.max(item.avg_score / item.full_score, 0), 1) : 0;
    return {
      ...item,
      options: item.options || [],
      score_rate: Math.round(scoreRate * 10000) / 10000,
      loss_rate: Math.round((1 - scoreRate) * 10000) / 10000,
      severity: severityFromRate(scoreRate),
    };
  });

  const buckets = new Map<string, { name: string; full: number; avg: number; questionNos: string[] }>();
  for (const question of normalizedQuestions) {
    for (const point of question.confirmed_knowledge_points) {
      const current = buckets.get(point.code) || { name: point.name, full: 0, avg: 0, questionNos: [] };
      current.full += question.full_score;
      current.avg += question.avg_score;
      current.questionNos.push(question.question_no);
      buckets.set(point.code, current);
    }
  }

  const knowledgeDiagnostics = Array.from(buckets.entries())
    .map(([code, bucket]) => {
      const scoreRate = bucket.full ? bucket.avg / bucket.full : 0;
      const rounded = Math.round(scoreRate * 10000) / 10000;
      return {
        code,
        name: bucket.name,
        score_rate: rounded,
        loss_rate: Math.round((1 - scoreRate) * 10000) / 10000,
        severity: severityFromRate(scoreRate),
        related_question_nos: bucket.questionNos,
        suggestion: suggestionFor(bucket.name, scoreRate),
      };
    })
    .sort((a, b) => a.score_rate - b.score_rate);

  const p3SearchRequests = knowledgeDiagnostics
    .filter((item) => item.severity !== "stable")
    .slice(0, 8)
    .map((item) => ({
      knowledge_point_codes: [item.code],
      knowledge_point_ids: [],
      question_type: null,
      difficulty_range: [0.35, 0.75] as [number, number],
      limit: 5,
      exclude_question_ids: normalizedQuestions
        .filter((question) => question.confirmed_knowledge_points.some((point) => point.code === item.code))
        .map((question) => question.question_id)
        .filter((value): value is string => Boolean(value)),
    }));

  const totalFull = normalizedQuestions.reduce((sum, item) => sum + item.full_score, 0);
  const totalAvg = normalizedQuestions.reduce((sum, item) => sum + item.avg_score, 0);
  const avgRate = totalFull ? totalAvg / totalFull : 0;
  const tagCoverage = normalizedQuestions.length
    ? normalizedQuestions.filter((item) => item.confirmed_knowledge_points.length > 0).length / normalizedQuestions.length
    : 0;
  const priority = normalizedQuestions.slice().sort((a, b) => a.score_rate - b.score_rate).slice(0, 6);
  const weak = knowledgeDiagnostics.filter((item) => item.severity === "critical" || item.severity === "weak").slice(0, 6);
  const reportLines = [
    `# ${analysis.teaching_report.title || "教师端分析报告"}`,
    "",
    `班级：${analysis.class_name}`,
    `整体得分率：${pct(avgRate)}`,
    `知识点覆盖率：${pct(tagCoverage)}`,
    "",
    "## 优先讲评题",
    ...priority.map(
      (item) => `- ${item.question_no}：得分率 ${pct(item.score_rate)}，知识点：${knowledgeNames(item.confirmed_knowledge_points)}`,
    ),
    "",
    "## 薄弱知识点",
    ...weak.map(
      (item) => `- ${item.name}：得分率 ${pct(item.score_rate)}，涉及题号 ${item.related_question_nos.join(", ")}。${item.suggestion}`,
    ),
  ];

  return {
    ...analysis,
    knowledge_tag_coverage: Math.round(tagCoverage * 10000) / 10000,
    question_analysis: normalizedQuestions.sort((a, b) => a.score_rate - b.score_rate),
    knowledge_diagnostics: knowledgeDiagnostics,
    p3_search_requests: p3SearchRequests,
    practice_recommendations: analysis.practice_recommendations ?? [],
    teaching_report: {
      ...analysis.teaching_report,
      summary: `本次分析匹配 ${normalizedQuestions.length} 道题，整体得分率 ${pct(avgRate)}，知识点覆盖率 ${pct(tagCoverage)}。`,
      priority_question_nos: priority.map((item) => item.question_no),
      weak_knowledge_points: weak.map((item) => item.name),
      markdown: reportLines.join("\n"),
    },
  };
}

async function apiGet<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { headers: campusHeaders() });
  if (!response.ok) throw new Error(path);
  return response.json();
}

async function apiEnvelopeRequest<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: campusHeaders(init?.headers),
    });
  } catch (err) {
    const reason = err instanceof Error ? err.message : "网络异常";
    throw new Error(`请求 ${path} 失败：${reason}`);
  }
  if (!response.ok) {
    let message = "请求失败";
    try {
      const payload = await response.json();
      message = payload?.detail?.message || payload?.message || message;
    } catch {
      message = response.statusText || message;
    }
    throw new Error(`${path} 返回 ${response.status}：${message}`);
  }
  const payload = (await response.json()) as ApiEnvelope<T>;
  return payload.data;
}

async function apiEnvelopeRequestWithTimeout<T>(
  path: string,
  init: RequestInit | undefined,
  timeoutMs: number,
  timeoutMessage: string,
): Promise<T> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await apiEnvelopeRequest<T>(path, { ...init, signal: controller.signal });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      const timeoutError = new Error(timeoutMessage);
      timeoutError.name = "RequestTimeoutError";
      throw timeoutError;
    }
    throw err;
  } finally {
    window.clearTimeout(timer);
  }
}

function sleep(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

async function apiStudentEnvelopeRequest<T>(path: string, studentId: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: studentHeaders(studentId, init?.headers),
  });
  if (!response.ok) {
    let message = path;
    try {
      const payload = await response.json();
      message = payload?.detail?.message || payload?.message || message;
    } catch {
      message = response.statusText || message;
    }
    throw new Error(message);
  }
  const payload = (await response.json()) as ApiEnvelope<T>;
  return payload.data;
}

function campusHeaders(extra?: HeadersInit): Headers {
  const headers = new Headers(extra);
  headers.set("X-Tenant-Id", CLIENT_CONTEXT.tenantId);
  headers.set("X-Teacher-Id", CLIENT_CONTEXT.teacherId);
  headers.set("X-Client-Role", "teacher");
  if (CLIENT_CONTEXT.authToken) headers.set("Authorization", `Bearer ${CLIENT_CONTEXT.authToken}`);
  return headers;
}

function studentHeaders(studentId: string, extra?: HeadersInit): Headers {
  const headers = new Headers(extra);
  headers.set("X-Tenant-Id", CLIENT_CONTEXT.tenantId);
  headers.set("X-Student-Id", studentId || CLIENT_CONTEXT.studentId);
  headers.set("X-Client-Role", "student");
  if (CLIENT_CONTEXT.authToken) headers.set("Authorization", `Bearer ${CLIENT_CONTEXT.authToken}`);
  return headers;
}

function safeLocalStorage(key: string): string {
  try {
    return window.localStorage.getItem(key) || "";
  } catch {
    return "";
  }
}

function setSafeLocalStorage(key: string, value: string) {
  try {
    if (value) window.localStorage.setItem(key, value);
    else window.localStorage.removeItem(key);
  } catch {
    // Ignore storage failures in restricted browser contexts.
  }
}

const THEME_STORAGE_KEY = "campus_theme";
type ThemeMode = "light" | "dark";

function readStoredTheme(): ThemeMode {
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
    if (stored === "light" || stored === "dark") return stored;
  } catch {
    // ignore
  }
  if (typeof window !== "undefined" && window.matchMedia) {
    if (window.matchMedia("(prefers-color-scheme: light)").matches) return "light";
    return "dark";
  }
  return "dark";
}

function applyTheme(theme: ThemeMode) {
  if (typeof document === "undefined") return;
  document.documentElement.setAttribute("data-theme", theme);
}

applyTheme(readStoredTheme());

function ThemeToggle() {
  const [theme, setTheme] = React.useState<ThemeMode>(() => readStoredTheme());

  React.useEffect(() => {
    applyTheme(theme);
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, theme);
    } catch {
      // ignore
    }
  }, [theme]);

  const next = theme === "dark" ? "light" : "dark";
  return (
    <button
      type="button"
      className="theme-toggle"
      aria-label={`切换到${next === "dark" ? "深色" : "浅色"}模式`}
      title={`切换到${next === "dark" ? "深色" : "浅色"}模式`}
      onClick={() => setTheme(next)}
    >
      <svg className="icon-sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <circle cx="12" cy="12" r="4" />
        <path d="M12 2v2" />
        <path d="M12 20v2" />
        <path d="m4.93 4.93 1.41 1.41" />
        <path d="m17.66 17.66 1.41 1.41" />
        <path d="M2 12h2" />
        <path d="M20 12h2" />
        <path d="m4.93 19.07 1.41-1.41" />
        <path d="m17.66 6.34 1.41-1.41" />
      </svg>
      <svg className="icon-moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
      </svg>
    </button>
  );
}

function IdentitySwitcher({ mode, displayStudentId }: { mode: "teacher" | "student" | "admin"; displayStudentId?: string }) {
  const [open, setOpen] = React.useState(false);
  const [tenantId, setTenantId] = React.useState(CLIENT_CONTEXT.tenantId);
  const [teacherId, setTeacherId] = React.useState(CLIENT_CONTEXT.teacherId);
  const [studentId, setStudentId] = React.useState(displayStudentId || CLIENT_CONTEXT.studentId);
  const [authToken, setAuthToken] = React.useState(CLIENT_CONTEXT.authToken);

  function saveIdentity() {
    setSafeLocalStorage("campus_tenant_id", tenantId.trim() || "campus_school");
    setSafeLocalStorage("campus_teacher_id", teacherId.trim() || "teacher");
    setSafeLocalStorage("campus_student_id", studentId.trim() || "student");
    setSafeLocalStorage("campus_demo_auth_token", authToken.trim());
    window.location.reload();
  }

  function resetIdentity() {
    setSafeLocalStorage("campus_tenant_id", "");
    setSafeLocalStorage("campus_teacher_id", "");
    setSafeLocalStorage("campus_student_id", "");
    setSafeLocalStorage("campus_demo_auth_token", "");
    window.location.reload();
  }

  const primaryLabel = mode === "student" ? "学生账号" : mode === "admin" ? "管理账号" : "教师账号";

  return (
    <div className="identity-switcher">
      <button type="button" onClick={() => setOpen((value) => !value)} aria-expanded={open}>
        <span>账号</span>
        <strong>{primaryLabel}</strong>
      </button>
      {open ? (
        <div className="identity-panel" role="dialog" aria-label="身份设置">
          <label>
            <span>学校 / 租户</span>
            <input value={tenantId} onChange={(event) => setTenantId(event.target.value)} />
          </label>
          <label>
            <span>教师 ID</span>
            <input value={teacherId} onChange={(event) => setTeacherId(event.target.value)} />
          </label>
          <label>
            <span>学生 ID</span>
            <input value={studentId} onChange={(event) => setStudentId(event.target.value)} />
          </label>
          <label>
            <span>访问令牌</span>
            <input
              type="password"
              placeholder="未开启受控模式时可留空"
              value={authToken}
              onChange={(event) => setAuthToken(event.target.value)}
            />
          </label>
          <div className="identity-actions">
            <button className="primary" type="button" onClick={saveIdentity}>
              保存身份
            </button>
            <button type="button" onClick={resetIdentity}>
              恢复默认
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function App({ adminMode = false }: { adminMode?: boolean }) {
  const [analysis, setAnalysis] = React.useState<P2ExamAnalysis | null>(null);
  const [examItems, setExamItems] = React.useState<ExamSummary[]>([]);
  const [activeExamId, setActiveExamId] = React.useState("");
  const [activeDiagnosticId, setActiveDiagnosticId] = React.useState("");
  const [lessonDownloadUrl, setLessonDownloadUrl] = React.useState("");
  const [practicePacks, setPracticePacks] = React.useState<PracticePackResult[]>([]);
  const [workflowMessage, setWorkflowMessage] = React.useState("");
  const [paperFile, setPaperFile] = React.useState<File | null>(null);
  const [scoreFile, setScoreFile] = React.useState<File | null>(null);
  const [examId, setExamId] = React.useState(makeExamId);
  const [className, setClassName] = React.useState("");
  const [stage, setStage] = React.useState<Stage>("senior_high");
  const [questionFilter, setQuestionFilter] = React.useState<QuestionFilter>("priority");
  const [selectedQuestionNo, setSelectedQuestionNo] = React.useState("");
  const [questionDraft, setQuestionDraft] = React.useState<QuestionDraft | null>(null);
  const [stemRawEditing, setStemRawEditing] = React.useState(false);
  const [optionRawEditing, setOptionRawEditing] = React.useState(false);
  const [activeSection, setActiveSection] = React.useState<TeacherNavSection>("workspace");
  const [calibrationStartedAt, setCalibrationStartedAt] = React.useState<number | null>(null);
  const [calibrationEndedAt, setCalibrationEndedAt] = React.useState<number | null>(null);
  const [calibrationStatus, setCalibrationStatus] = React.useState<CalibrationNavState["status"]>("idle");
  const [calibrationMessage, setCalibrationMessage] = React.useState("");
  const [clockNow, setClockNow] = React.useState(Date.now());
  const [editingRecommendationKey, setEditingRecommendationKey] = React.useState("");
  const [recommendationDraft, setRecommendationDraft] = React.useState<RecommendationDraft | null>(null);
  const [studentFlow, setStudentFlow] = React.useState<StudentFlowState | null>(null);
  const [generatedReviewItems, setGeneratedReviewItems] = React.useState<GeneratedQuestionAuditItem[]>([]);
  const [auditSource, setAuditSource] = React.useState("");
  const [auditLogs, setAuditLogs] = React.useState<AuditLogItem[]>([]);
  const [readiness, setReadiness] = React.useState<DemoReadiness | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [confirming, setConfirming] = React.useState(false);
  const [studentBusy, setStudentBusy] = React.useState(false);
  const [auditBusy, setAuditBusy] = React.useState(false);
  const [downloading, setDownloading] = React.useState(false);
  const [knowledgeTagging, setKnowledgeTagging] = React.useState(false);
  const [error, setError] = React.useState("");

  React.useEffect(() => {
    void loadExamList();
    void loadReadiness();
    if (adminMode) {
      void loadGeneratedQuestionReviews();
      void loadAuditLogs();
    }
  }, [adminMode]);

  React.useEffect(() => {
    if (!analysis?.question_analysis.length) {
      setSelectedQuestionNo("");
      setQuestionDraft(null);
      setStemRawEditing(false);
      setOptionRawEditing(false);
      return;
    }
    const orderedQuestions = sortQuestionsForTeacher(analysis.question_analysis);
    const current =
      orderedQuestions.find((item) => item.question_no === selectedQuestionNo) || orderedQuestions[0];
    if (current.question_no !== selectedQuestionNo) setSelectedQuestionNo(current.question_no);
    setQuestionDraft(draftFromQuestion(current));
  }, [analysis, selectedQuestionNo]);

  React.useEffect(() => {
    if (adminMode) return;
    const sectionIds: TeacherNavSection[] = ["workspace", "review", "questions", "knowledge", "practice", "report"];
    function updateActiveSection() {
      const viewportAnchor = 140;
      let current: TeacherNavSection = "workspace";
      for (const sectionId of sectionIds) {
        const element = document.getElementById(sectionId);
        if (!element) continue;
        if (element.getBoundingClientRect().top <= viewportAnchor) current = sectionId;
      }
      setActiveSection(current);
    }
    updateActiveSection();
    window.addEventListener("scroll", updateActiveSection, { passive: true });
    window.addEventListener("resize", updateActiveSection);
    return () => {
      window.removeEventListener("scroll", updateActiveSection);
      window.removeEventListener("resize", updateActiveSection);
    };
  }, [adminMode, analysis]);

  React.useEffect(() => {
    if (typeof window === "undefined" || typeof IntersectionObserver === "undefined") return;
    const targets = document.querySelectorAll(
      "section, .teacher-hero, .student-hero, .admin-header, .workspace-main, .status-card, .delivery-card, .collapsible-section, .empty-outcome, .question-card, .knowledge-card, .student-card, .student-history-shell, .student-report-card, .student-wrong-card, .student-progress-cards article, .student-progress-detail article, .student-practice-card, .audit-card, .report-preview",
    );
    if (!targets.length) return;
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            entry.target.classList.add("in-view");
            observer.unobserve(entry.target);
          }
        }
      },
      { threshold: 0.08, rootMargin: "0px 0px -8% 0px" },
    );
    targets.forEach((node) => observer.observe(node));
    return () => observer.disconnect();
  }, [analysis, adminMode]);

  React.useEffect(() => {
    if (calibrationStatus !== "running") return;
    const timer = window.setInterval(() => setClockNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [calibrationStatus]);

  async function loadDemo() {
    setBusy(true);
    setError("");
    try {
      setAnalysis(rebuildAnalysis(await apiGet<P2ExamAnalysis>("/api/p2/demo")));
      setActiveExamId("");
      setActiveDiagnosticId("");
      setLessonDownloadUrl("");
      setPracticePacks([]);
      setWorkflowMessage("分析结果已生成，可继续查看完整效果。");
      setQuestionFilter("priority");
    } catch {
      setError("后端服务未连接，请先启动本地服务后刷新页面。");
    } finally {
      setBusy(false);
    }
  }

  async function loadExamList() {
    try {
      const data = await apiEnvelopeRequest<{ items: ExamSummary[] }>("/exams?limit=8");
      setExamItems(data.items);
    } catch {
      setExamItems([]);
    }
  }

  async function deleteExam(item: ExamSummary) {
    if (busy) return;
    const label = item.name || item.exam_id;
    const confirmed = window.confirm(`确认删除「${label}」的诊断记录？该操作不可撤销。`);
    if (!confirmed) return;
    setBusy(true);
    setError("");
    try {
      setWorkflowMessage("正在删除诊断记录");
      await apiEnvelopeRequest<{ exam_id: string; status: string; removed_files: number; removed_diagnostics: number }>(
        `/exams/${item.exam_id}`,
        { method: "DELETE" },
      );
      const wasActive = activeExamId === item.exam_id;
      setExamItems((current) => current.filter((entry) => entry.exam_id !== item.exam_id));
      if (wasActive) {
        setAnalysis(null);
        setActiveExamId("");
        setActiveDiagnosticId("");
        setLessonDownloadUrl("");
        setSelectedQuestionNo("");
        setQuestionDraft(null);
      }
      setWorkflowMessage(`已删除 ${label}。`);
      await Promise.allSettled([loadExamList(), loadReadiness(), loadAuditLogs()]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除失败");
      setWorkflowMessage("");
    } finally {
      setBusy(false);
    }
  }

  async function loadReadiness() {
    try {
      const data = await apiEnvelopeRequest<DemoReadiness>("/api/demo/readiness");
      setReadiness(data);
    } catch {
      setReadiness(null);
    }
  }

  async function loadGeneratedQuestionReviews() {
    try {
      const data = await apiEnvelopeRequest<GeneratedQuestionAuditList>(
        "/ai-generated-questions?status=pending_review&limit=20",
      );
      setGeneratedReviewItems(data.items);
      setAuditSource(data.source);
    } catch {
      setGeneratedReviewItems([]);
      setAuditSource("");
    }
  }

  async function loadAuditLogs() {
    try {
      const data = await apiEnvelopeRequest<{ items: AuditLogItem[] }>("/audit-logs?limit=24");
      setAuditLogs(data.items);
    } catch {
      setAuditLogs([]);
    }
  }

  async function openExam(item: ExamSummary) {
    if (!item.question_count) {
      setError("这场考试还没有完成解析。");
      return;
    }
    setBusy(true);
    setError("");
    try {
      setWorkflowMessage("正在恢复历史考试");
      const loaded = await apiEnvelopeRequest<P2ExamAnalysis>(`/exams/${item.exam_id}/analysis`);
      setAnalysis(rebuildAnalysis(loaded));
      setActiveExamId(item.exam_id);
      setActiveDiagnosticId(item.latest_lesson_plan?.diagnostic_id || item.diagnostic_ids[0] || "");
      setLessonDownloadUrl(item.latest_lesson_plan?.download_url || "");
      await loadPracticePacks(item.exam_id);
      setExamId(item.exam_id);
      setClassName("");
      setQuestionFilter("priority");
      setWorkflowMessage(`已打开 ${item.name || item.exam_id}。`);
    } catch (err) {
      setWorkflowMessage("");
      setError(err instanceof Error ? err.message : "历史考试加载失败");
    } finally {
      setBusy(false);
    }
  }

  async function loadPracticePacks(examId: string) {
    try {
      const data = await apiEnvelopeRequest<{ items: PracticePackResult[] }>(`/exams/${examId}/practice-packs`);
      setPracticePacks(data.items);
    } catch {
      setPracticePacks([]);
    }
  }

  async function runAiKnowledgeCalibration() {
    if (!analysis || !activeExamId) {
      setError("请先完成一次试卷分析。");
      return;
    }
    setKnowledgeTagging(true);
    setError("");
    const calibrationStart = Date.now();
    setClockNow(calibrationStart);
    setCalibrationStartedAt(calibrationStart);
    setCalibrationEndedAt(null);
    setCalibrationStatus("running");
    setCalibrationMessage("正在逐题矫正整套试卷的知识点");
    try {
      setWorkflowMessage("正在启动全卷智能矫正");
      const started = await apiEnvelopeRequest<AiKnowledgeTagJob>(`/exams/${activeExamId}/knowledge-tags/ai`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scope: "all" }),
      });
      let latest = started;
      for (let index = 0; index < 90; index += 1) {
        if (latest.status === "succeeded" || latest.status === "failed") break;
        await sleep(2000);
        latest = await apiEnvelopeRequest<AiKnowledgeTagJob>(
          `/exams/${activeExamId}/knowledge-tags/ai/${started.job_id}`,
        );
        setCalibrationMessage(latest.message || "正在智能矫正");
        setWorkflowMessage(latest.message || "正在智能矫正");
      }
      if (latest.status === "failed") {
        throw new Error(latest.error || latest.message || "智能矫正失败");
      }
      if (latest.status !== "succeeded") {
        setWorkflowMessage("智能矫正仍在后台运行，可稍后刷新分析结果。");
        setCalibrationMessage("智能矫正仍在后台运行");
        return;
      }

      const loaded = await apiEnvelopeRequest<P2ExamAnalysis>(`/exams/${activeExamId}/analysis`);
      const nextAnalysis = rebuildAnalysis(loaded);
      setAnalysis(nextAnalysis);
      const refreshedQuestion =
        nextAnalysis.question_analysis.find((item) => item.question_no === selectedQuestionNo) ||
        sortQuestionsForTeacher(nextAnalysis.question_analysis)[0];
      if (refreshedQuestion) {
        setSelectedQuestionNo(refreshedQuestion.question_no);
        setQuestionDraft(draftFromQuestion(refreshedQuestion));
        setStemRawEditing(false);
        setOptionRawEditing(false);
      }
      setEditingRecommendationKey("");
      setRecommendationDraft(null);
      setCalibrationStatus("succeeded");
      setCalibrationEndedAt(Date.now());
      setCalibrationMessage(`已更新 ${latest.updated_count} / ${latest.total_count} 道题`);
      setWorkflowMessage(`智能矫正完成，已更新 ${latest.updated_count} / ${latest.total_count} 道题。`);
      await loadExamList();
      await loadReadiness();
      if (adminMode) await loadAuditLogs();
    } catch (err) {
      setWorkflowMessage("");
      setCalibrationStatus("failed");
      setCalibrationEndedAt(Date.now());
      setCalibrationMessage(err instanceof Error ? err.message : "智能矫正失败");
      setError(err instanceof Error ? err.message : "智能矫正失败");
    } finally {
      setKnowledgeTagging(false);
    }
  }

  async function createPracticePackFromRecommendations() {
    if (!analysis || !activeExamId || !activeDiagnosticId) {
      setError("请先完成考试诊断。");
      return;
    }
    setBusy(true);
    setError("");
    try {
      setWorkflowMessage("正在生成练习包");
      const payload = await apiEnvelopeRequest<{ practice_pack: PracticePackResult }>(
        `/exams/${activeExamId}/practice-packs`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            diagnostic_id: activeDiagnosticId,
            title: `${analysis.class_name || "班级"} 薄弱知识点练习包`,
            target: "class",
            target_ref_id: analysis.class_name || activeExamId,
            created_by: CLIENT_CONTEXT.teacherId,
          }),
        },
      );
      setPracticePacks((current) => [payload.practice_pack, ...current]);
      setWorkflowMessage(payload.practice_pack.message || "练习包已生成。");
      await loadExamList();
      await loadReadiness();
    } catch (err) {
      setWorkflowMessage("");
      setError(err instanceof Error ? err.message : "练习包生成失败");
    } finally {
      setBusy(false);
    }
  }

  function startRecommendationEdit(group: PracticeRecommendationGroup, item: QuestionRecommendation) {
    setEditingRecommendationKey(recommendationKey(group, item));
    setRecommendationDraft(draftFromRecommendation(item));
  }

  function cancelRecommendationEdit() {
    setEditingRecommendationKey("");
    setRecommendationDraft(null);
  }

  async function saveRecommendationEdit(group: PracticeRecommendationGroup, item: QuestionRecommendation) {
    if (!analysis || !recommendationDraft) return;
    const difficulty = Number(recommendationDraft.difficulty);
    if (!Number.isFinite(difficulty) || difficulty < 0 || difficulty > 1) {
      setError("推荐题难度需要填写 0 到 1 之间的数字。");
      return;
    }
    const key = recommendationKey(group, item);
    const updatedItem = {
      content_html: editableTextToHtml(recommendationDraft.content_text),
      answer_html: editableTextToHtml(recommendationDraft.answer_text),
      analysis_html: editableTextToHtml(recommendationDraft.analysis_text),
      recommend_reason: recommendationDraft.recommend_reason.trim(),
      question_type: recommendationDraft.question_type.trim() || item.question_type,
      difficulty: Math.round(difficulty * 1000) / 1000,
    };
    if (activeExamId) {
      setError("");
      setWorkflowMessage("正在保存推荐题");
      try {
        const saved = await apiEnvelopeRequest<{ analysis: P2ExamAnalysis }>(
          `/exams/${activeExamId}/practice-recommendations/${encodeURIComponent(group.knowledge_point_code || group.knowledge_point_id || group.knowledge_point_name)}/items/${encodeURIComponent(item.bank_question_id)}`,
          {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(updatedItem),
          },
        );
        setAnalysis(rebuildAnalysis(saved.analysis));
        setEditingRecommendationKey("");
        setRecommendationDraft(null);
        setWorkflowMessage("推荐题已保存，导出报告与练习包会同步使用。");
        await loadExamList();
        return;
      } catch (err) {
        setWorkflowMessage("");
        setError(err instanceof Error ? err.message : "推荐题保存失败");
        return;
      }
    }
    const nextPracticeRecommendations = (analysis.practice_recommendations ?? []).map((currentGroup) => ({
      ...currentGroup,
      items: currentGroup.items.map((currentItem) => {
        if (recommendationKey(currentGroup, currentItem) !== key) return currentItem;
        return {
          ...currentItem,
          ...updatedItem,
        };
      }),
    }));
    setAnalysis(
      rebuildAnalysis({
        ...analysis,
        practice_recommendations: nextPracticeRecommendations,
      }),
    );
    setEditingRecommendationKey("");
    setRecommendationDraft(null);
    setWorkflowMessage("推荐题已更新。");
  }

  async function runStudentPreview() {
    setStudentBusy(true);
    setError("");
    try {
      const started = await apiEnvelopeRequest<{ job_id: string }>("/api/ai/v1/wrong-question/recognize", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          student_id: "student_demo",
          file: {
            file_id: "demo_wrong_image",
            storage_uri: "local://demo/triangle_wrong_question.png",
            file_name: "triangle_wrong_question.png",
            mime_type: "image/png",
            size_bytes: 128,
            sha256: "demo",
          },
          options: {
            subject: "math",
            grade: "8",
          },
        }),
      });
      const job = await apiEnvelopeRequest<P1JobStatus>(`/api/ai/v1/jobs/${started.job_id}`);
      const recognized = await apiEnvelopeRequest<WrongQuestionRecognitionResult>(
        `/api/ai/v1/wrong-question/recognize/${started.job_id}/result`,
      );
      if (recognized.status !== "succeeded" || !recognized.result) {
        throw new Error(recognized.error || "错题识别未返回有效结果");
      }

      const question = recognized.result.question;
      const questionHtml = question.stem_html || stemTextToHtml(question.stem_text || "");
      const knowledgePointIds = recognized.result.knowledge_candidates
        .map((item) => item.knowledge_point_id)
        .filter(Boolean);
      const guided = await apiEnvelopeRequest<GuidedExplanationResult>("/api/ai/v1/explanations/guided/next", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          student_id: "student_demo",
          wrong_question_id: started.job_id,
          question_html: questionHtml,
          knowledge_point_ids: knowledgePointIds,
          current_step_index: 0,
          student_input: "",
          mode: "hint",
        }),
      });
      const generated = await apiEnvelopeRequest<VariantGenerationResult>("/api/ai/v1/questions/variants/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source_question_id: started.job_id,
          source_question_html: questionHtml,
          knowledge_point_ids: knowledgePointIds,
          difficulty_target: 0.55,
          count: 2,
          constraints: {
            stage: "junior_high",
            preserve_core_skill: true,
          },
        }),
      });

      setStudentFlow({
        jobId: started.job_id,
        jobStatus: job.status,
        questionHtml,
        questionText: question.stem_text,
        questionType: question.question_type,
        parseConfidence: question.parse_confidence,
        candidates: recognized.result.knowledge_candidates,
        guided,
        variants: generated.items,
        variantSource: generated.source,
        updatedAt: new Date().toLocaleTimeString(),
      });
      setWorkflowMessage("学生端错题练习预览已生成。");
    } catch (err) {
      setWorkflowMessage("");
      setError(err instanceof Error ? err.message : "学生端预览生成失败");
    } finally {
      setStudentBusy(false);
    }
  }

  async function submitStudentVariantsForReview() {
    if (!studentFlow?.variants.length) {
      setError("请先生成学生侧变式题。");
      return;
    }
    const fallbackKnowledgeIds = studentFlow.candidates.map((item) => item.knowledge_point_id).filter(Boolean);
    if (!fallbackKnowledgeIds.length && !studentFlow.variants.some((item) => item.knowledge_point_ids.length)) {
      setError("变式题缺少知识点，不能进入审核。");
      return;
    }

    setAuditBusy(true);
    setError("");
    try {
      const result = await apiEnvelopeRequest<{
        saved_count: number;
        audit_status: string;
        source: string;
        message?: string;
      }>("/ai-generated-questions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source_question_id: studentFlow.jobId,
          model_name: studentFlow.variantSource || "p2-generated-variant",
          prompt_version: "p2.student-preview.v1",
          raw_request: {
            student_question_type: studentFlow.questionType,
            generated_at: studentFlow.updatedAt,
          },
          items: studentFlow.variants.map((variant) => ({
            generated_question_id: variant.generated_question_id,
            content_html: variant.content_html,
            answer_html: variant.answer_html,
            analysis_html: variant.analysis_html,
            knowledge_point_ids: variant.knowledge_point_ids.length ? variant.knowledge_point_ids : fallbackKnowledgeIds,
            question_type: variant.question_type || studentFlow.questionType || "solution",
            difficulty: variant.difficulty,
            validation: {
              audit_status: variant.audit_status,
              source: studentFlow.variantSource,
            },
          })),
        }),
      });
      await loadGeneratedQuestionReviews();
      await loadAuditLogs();
      setWorkflowMessage(result.message || `${result.saved_count} 道 AI 生成题已进入教师审核。`);
    } catch (err) {
      setWorkflowMessage("");
      setError(err instanceof Error ? err.message : "AI 生成题送审失败");
    } finally {
      setAuditBusy(false);
    }
  }

  async function reviewGeneratedQuestion(generatedQuestionId: string, decision: "approved" | "rejected") {
    setAuditBusy(true);
    setError("");
    try {
      const result = await apiEnvelopeRequest<GeneratedQuestionReviewResult>(
        `/ai-generated-questions/${generatedQuestionId}/review`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            decision,
            reviewer_id: CLIENT_CONTEXT.teacherId,
            review_comment: decision === "approved" ? "题目逻辑正确，适合课堂强化。" : "暂不进入题库。",
            publish_to_bank: decision === "approved",
          }),
        },
      );
      await loadGeneratedQuestionReviews();
      await loadReadiness();
      await loadAuditLogs();
      setWorkflowMessage(
        result.message ||
          (decision === "approved"
            ? `已审核通过，题库编号 ${result.bank_question_id || "待同步"}。`
            : "已驳回该 AI 生成题。"),
      );
    } catch (err) {
      setWorkflowMessage("");
      setError(err instanceof Error ? err.message : "AI 生成题审核失败");
    } finally {
      setAuditBusy(false);
    }
  }

  async function uploadExamFile(examId: string, fileType: "paper" | "score_excel", file: File) {
    const data = new FormData();
    data.append("file_type", fileType);
    data.append("file", file);
    return apiEnvelopeRequest<UploadedFilePayload>(`/exams/${examId}/files`, {
      method: "POST",
      body: data,
    });
  }

  async function runAnalysis() {
    if (!paperFile || !scoreFile) {
      setError("请先选择试卷文件和成绩表。");
      return;
    }

    setBusy(true);
    setError("");
    setLessonDownloadUrl("");
    const examName = examId.trim() || makeExamId();
    const classLabel = className.trim() || "未命名班级";

    try {
      setWorkflowMessage("正在创建考试");
      const created = await apiEnvelopeRequest<{ exam_id: string; status: string }>("/exams", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: examName,
          subject: "math",
          grade: stage === "junior_high" ? "junior_high" : "senior_high",
          class_ids: [classLabel],
          exam_date: new Date().toISOString().slice(0, 10),
          teacher_id: CLIENT_CONTEXT.teacherId,
        }),
      });

      setActiveExamId(created.exam_id);
      setExamId(created.exam_id);

      setWorkflowMessage("正在上传试卷和成绩");
      const [paperUpload, scoreUpload] = await Promise.all([
        uploadExamFile(created.exam_id, "paper", paperFile),
        uploadExamFile(created.exam_id, "score_excel", scoreFile),
      ]);

      setWorkflowMessage("正在解析试卷");
      const parsed = await apiEnvelopeRequest<{ status: string; warnings?: string[] }>(
        `/exams/${created.exam_id}/parse`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            paper_file_id: paperUpload.file.file_id,
            score_file_id: scoreUpload.file.file_id,
            auto_tag_knowledge: true,
          }),
        },
      );
      if (parsed.status !== "teacher_review") {
        throw new Error(parsed.warnings?.join("；") || "解析结果需要处理");
      }

      setWorkflowMessage("正在生成诊断");
      try {
        const diagnostic = await apiEnvelopeRequestWithTimeout<{ diagnostic_id: string; status: string }>(
          `/exams/${created.exam_id}/diagnostics/run`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              analysis_scope: "class",
              class_id: classLabel,
              include_teaching_suggestions: true,
              include_question_recommendations: true,
            }),
          },
          25000,
          "诊断生成较慢，已先载入题目分析。",
        );
        setActiveDiagnosticId(diagnostic.diagnostic_id);
      } catch (err) {
        if (err instanceof Error && err.name === "RequestTimeoutError") {
          setWorkflowMessage(err.message);
        } else {
          throw err;
        }
      }

      setWorkflowMessage("正在加载分析结果");
      const standardAnalysis = await apiEnvelopeRequest<P2ExamAnalysis>(`/exams/${created.exam_id}/analysis`);
      setAnalysis(rebuildAnalysis(standardAnalysis));
      setPracticePacks(standardAnalysis.practice_packs ?? []);
      setWorkflowMessage("分析已完成并保存。");
      setQuestionFilter("priority");
      await loadExamList();
      await loadReadiness();
      await loadAuditLogs();
    } catch (err) {
      setError(err instanceof Error ? err.message : "分析失败");
      setWorkflowMessage("");
    } finally {
      setBusy(false);
    }
  }

  async function downloadReport(kind: "docx" | "markdown") {
    if (!analysis) return;
    setDownloading(true);
    setError("");
    try {
      if (kind === "docx" && activeExamId && activeDiagnosticId) {
        setWorkflowMessage("正在生成 Word 教案");
        const lesson = await apiEnvelopeRequest<{
          lesson_plan_id: string;
          status: string;
          file: { file_name: string; download_url: string };
        }>(`/exams/${activeExamId}/lesson-plans`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            diagnostic_id: activeDiagnosticId,
            template_id: "tpl_school_math_review_v1",
            sections: ["exam_summary", "high_loss_questions", "weakness_summary", "practice_recommendations"],
          }),
        });
        const downloadUrl = `${API_BASE}${lesson.file.download_url}`;
        const response = await fetch(downloadUrl, { headers: campusHeaders() });
        if (!response.ok) throw new Error("Word 教案下载失败");
        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = lesson.file.file_name;
        link.click();
        URL.revokeObjectURL(url);
        setLessonDownloadUrl(lesson.file.download_url);
        setWorkflowMessage("Word 教案已生成并保存。");
        await loadExamList();
        await loadReadiness();
        await loadAuditLogs();
        return;
      }

      const response = await fetch(`${API_BASE}/api/p2/reports/${kind === "docx" ? "docx" : "markdown"}`, {
        method: "POST",
        headers: campusHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify(analysis),
      });
      if (!response.ok) throw new Error(kind === "docx" ? "Word 导出失败" : "Markdown 导出失败");
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `${analysis.exam_id}-${kind === "docx" ? "教师讲评报告.docx" : "教师讲评报告.md"}`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : "报告导出失败");
    } finally {
      setDownloading(false);
    }
  }

  function selectQuestion(questionNo: string, scrollToReview = false) {
    const question = analysis?.question_analysis.find((item) => item.question_no === questionNo);
    setSelectedQuestionNo(questionNo);
    setStemRawEditing(false);
    setOptionRawEditing(false);
    if (question) setQuestionDraft(draftFromQuestion(question));
    if (scrollToReview) {
      window.setTimeout(() => document.getElementById("review")?.scrollIntoView({ behavior: "smooth", block: "start" }), 0);
    }
  }

  function resetQuestionDraft() {
    const question = analysis?.question_analysis.find((item) => item.question_no === selectedQuestionNo);
    if (question) setQuestionDraft(draftFromQuestion(question));
    setStemRawEditing(false);
    setOptionRawEditing(false);
  }

  async function saveQuestionReview() {
    if (!analysis || !questionDraft) return;
    const fullScore = Number(questionDraft.full_score);
    if (!Number.isFinite(fullScore) || fullScore <= 0) {
      setError("满分必须是大于 0 的数字。");
      return;
    }

    const currentQuestion = analysis.question_analysis.find((item) => item.question_no === selectedQuestionNo);
    const confirmedKnowledge = parseKnowledgePoints(questionDraft.knowledge_text);
    const questionImages = parseQuestionImages(questionDraft.image_text);
    const cleanStemText = normalizeQuestionTextForSave(questionDraft.stem_text, questionImages);
    const cleanOptions = normalizeOptionsForSave(parseQuestionOptions(questionDraft.option_text), questionImages);
    if (activeExamId && currentQuestion?.question_id) {
      setError("");
      setWorkflowMessage("正在保存教师确认");
      try {
        await apiEnvelopeRequest<{ updated: boolean }>(
          `/exams/${activeExamId}/questions/${currentQuestion.question_id}`,
          {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              question_no: questionDraft.question_no.trim() || currentQuestion.question_no,
              stem_text: cleanStemText,
              stem_html: stemTextToHtml(cleanStemText),
              question_type: questionDraft.question_type.trim() || null,
              full_score: fullScore,
              options: cleanOptions,
              images: questionImages,
            }),
          },
        );
        await apiEnvelopeRequest<{ knowledge_point_ids: string[] }>(
          `/exams/${activeExamId}/questions/${currentQuestion.question_id}/knowledge-tags`,
          {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              knowledge_point_ids: confirmedKnowledge.map((item) => item.code),
              comment: "teacher confirmed in frontend",
            }),
          },
        );
        const refreshed = await apiEnvelopeRequest<P2ExamAnalysis>(`/exams/${activeExamId}/analysis`);
        const next = rebuildAnalysis(refreshed);
        const savedQuestionNo = questionDraft.question_no.trim() || currentQuestion.question_no;
        const refreshedQuestion =
          next.question_analysis.find((item) => item.question_no === savedQuestionNo) ||
          next.question_analysis.find((item) => item.question_id === currentQuestion.question_id) ||
          sortQuestionsForTeacher(next.question_analysis)[0];
        setAnalysis(next);
        setSelectedQuestionNo(refreshedQuestion?.question_no || savedQuestionNo);
        if (refreshedQuestion) setQuestionDraft(draftFromQuestion(refreshedQuestion));
        setStemRawEditing(false);
        setOptionRawEditing(false);
        setEditingRecommendationKey("");
        setRecommendationDraft(null);
        setWorkflowMessage("教师确认已保存，推荐题已同步更新。");
        await loadExamList();
        await loadAuditLogs();
        return;
      } catch (err) {
        setWorkflowMessage("");
        setError(err instanceof Error ? err.message : "保存失败");
        return;
      }
    }

    const next = rebuildAnalysis({
      ...analysis,
      question_analysis: analysis.question_analysis.map((item) => {
        if (item.question_no !== selectedQuestionNo) return item;
        return {
          ...item,
          question_no: questionDraft.question_no.trim() || item.question_no,
          stem_text: cleanStemText,
          stem_markdown: cleanStemText,
          options: cleanOptions,
          question_type: questionDraft.question_type.trim() || null,
          full_score: fullScore,
          images: questionImages,
          confirmed_knowledge_points: confirmedKnowledge,
          teacher_review_status: "confirmed",
          needs_review: false,
          warnings: [],
        };
      }),
    });
    const savedQuestionNo = questionDraft.question_no.trim() || selectedQuestionNo;
    setError("");
    setAnalysis(next);
    setSelectedQuestionNo(savedQuestionNo);
    setStemRawEditing(false);
    setOptionRawEditing(false);
  }

  async function confirmAllQuestions() {
    if (!analysis) return;

    const activeDraft = questionDraft;
    const selectedDraftScore = activeDraft ? Number(activeDraft.full_score) : 0;
    if (activeDraft && (!Number.isFinite(selectedDraftScore) || selectedDraftScore <= 0)) {
      setError("当前题目的满分必须是大于 0 的数字。");
      return;
    }

    setConfirming(true);
    setError("");
    try {
      const updatedQuestions = sortQuestionsForTeacher(analysis.question_analysis).map((item) => {
        const isSelected = item.question_no === selectedQuestionNo && activeDraft;
        const knowledge = isSelected ? parseKnowledgePoints(activeDraft.knowledge_text) : item.confirmed_knowledge_points;
        const fullScore = isSelected ? selectedDraftScore : item.full_score;
        const images = isSelected ? parseQuestionImages(activeDraft.image_text) : item.images || [];
        const stemText = normalizeQuestionTextForSave(isSelected ? activeDraft.stem_text : questionDisplayText(item), images);
        const options = normalizeOptionsForSave(isSelected ? parseQuestionOptions(activeDraft.option_text) : item.options || [], images);
        return {
          ...item,
          question_no: isSelected ? activeDraft.question_no.trim() || item.question_no : item.question_no,
          stem_text: stemText,
          stem_markdown: stemText,
          question_type: isSelected ? questionDraft.question_type.trim() || null : item.question_type,
          full_score: fullScore,
          options,
          images,
          confirmed_knowledge_points: knowledge,
          teacher_review_status: "confirmed" as const,
          needs_review: false,
          warnings: [],
        };
      });

      if (activeExamId) {
        for (let index = 0; index < updatedQuestions.length; index += 1) {
          const item = updatedQuestions[index];
          if (!item.question_id) continue;
          setWorkflowMessage(`正在确认第 ${index + 1} / ${updatedQuestions.length} 题`);
          await apiEnvelopeRequest<{ updated: boolean }>(`/exams/${activeExamId}/questions/${item.question_id}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              question_no: item.question_no,
              stem_text: item.stem_text,
              stem_html: stemTextToHtml(item.stem_text),
              question_type: item.question_type,
              full_score: item.full_score,
              options: item.options || [],
              images: item.images || [],
            }),
          });
          await apiEnvelopeRequest<{ knowledge_point_ids: string[] }>(
            `/exams/${activeExamId}/questions/${item.question_id}/knowledge-tags`,
            {
              method: "PUT",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                knowledge_point_ids: item.confirmed_knowledge_points.map((point) => point.code),
                comment: "teacher confirmed all questions",
              }),
            },
          );
        }
      }

      const next = activeExamId
        ? rebuildAnalysis(await apiEnvelopeRequest<P2ExamAnalysis>(`/exams/${activeExamId}/analysis`))
        : rebuildAnalysis({
            ...analysis,
            question_analysis: updatedQuestions,
          });
      setAnalysis(next);
      const nextSelected =
        next.question_analysis.find((item) => item.question_no === selectedQuestionNo) ||
        sortQuestionsForTeacher(next.question_analysis)[0];
      setSelectedQuestionNo(nextSelected?.question_no || "");
      if (nextSelected) setQuestionDraft(draftFromQuestion(nextSelected));
      setStemRawEditing(false);
      setOptionRawEditing(false);
      setEditingRecommendationKey("");
      setRecommendationDraft(null);
      setWorkflowMessage("全部题目已确认，推荐题已同步更新，可导出讲评报告。");
      await loadExamList();
      if (adminMode) await loadAuditLogs();
    } catch (err) {
      setWorkflowMessage("");
      setError(err instanceof Error ? err.message : "确认全部题目失败");
    } finally {
      setConfirming(false);
    }
  }

  const overall = overallRate(analysis);
  const tagCoverage = knowledgeCoverage(analysis);
  const weakKnowledge = analysis?.knowledge_diagnostics.filter((item) => item.severity !== "stable") ?? [];
  const priorityQuestions = analysis?.question_analysis.slice(0, 6) ?? [];
  const confirmedCount =
    analysis?.question_analysis.filter((item) => item.teacher_review_status === "confirmed").length ?? 0;
  const recommendationCount = countRecommendations(analysis);
  const selectedQuestion = analysis?.question_analysis.find((item) => item.question_no === selectedQuestionNo) ?? null;
  const teacherQuestionList = sortQuestionsForTeacher(analysis?.question_analysis ?? []);
  const filteredQuestions =
    questionFilter === "priority"
      ? priorityQuestions
      : sortQuestionsForTeacher(
          analysis?.question_analysis.filter((item) => questionFilter === "all" || item.severity === questionFilter) ?? [],
        );
  const teacherKnowledgeDiagnostics = analysis?.knowledge_diagnostics ?? [];
  const teacherWeakKnowledgeDiagnostics = teacherKnowledgeDiagnostics.filter((item) => item.severity !== "stable");
  const visibleKnowledgeDiagnostics = adminMode
    ? teacherKnowledgeDiagnostics
    : (teacherWeakKnowledgeDiagnostics.length ? teacherWeakKnowledgeDiagnostics : teacherKnowledgeDiagnostics).slice(0, 9);
  const extraKnowledgeDiagnostics = adminMode
    ? []
    : (analysis?.knowledge_diagnostics ?? []).filter(
        (item) => !visibleKnowledgeDiagnostics.some((visible) => visible.code === item.code),
      );
  const calibrationTargetCount = analysis?.question_analysis.length ?? 0;
  const readinessFacts = readiness?.facts;
  const calibrationElapsedSeconds = calibrationStartedAt
    ? Math.round(((calibrationStatus === "running" ? clockNow : calibrationEndedAt || clockNow) - calibrationStartedAt) / 1000)
    : 0;
  const calibrationNavState: CalibrationNavState = {
    status: calibrationStatus,
    elapsedSeconds: calibrationElapsedSeconds,
    message: calibrationMessage,
  };
  const workflowSteps = adminMode
    ? [
        {
          label: "导入材料",
          detail: analysis ? "试卷与成绩已读取" : "上传 Word 试卷和成绩表",
          state: analysis ? "done" : busy ? "active" : "idle",
        },
        {
          label: "学情诊断",
          detail: analysis ? `${analysis.question_analysis.length} 道题已完成分析` : "生成逐题与知识点诊断",
          state: analysis ? "done" : "idle",
        },
        {
          label: "练习建议",
          detail: recommendationCount ? `${recommendationCount} 道推荐题可用` : "按薄弱知识点推荐同类练习",
          state: practicePacks.length ? "done" : recommendationCount ? "active" : "idle",
        },
        {
          label: "讲评教案",
          detail: lessonDownloadUrl ? "最近教案可下载" : "生成 Word 讲评材料",
          state: lessonDownloadUrl ? "done" : analysis ? "active" : "idle",
        },
      ]
    : [
        {
          label: "上传材料",
          detail: analysis ? "试卷与成绩已读取" : "选择 Word 试卷和成绩表",
          state: analysis ? "done" : busy ? "active" : "idle",
        },
        {
          label: "题目整理",
          detail: analysis ? `${analysis.question_analysis.length} 道题已整理` : "识别题干、表格、公式和题图",
          state: analysis ? "done" : "idle",
        },
        {
          label: "教师核对",
          detail: analysis ? `已确认 ${confirmedCount} / ${analysis.question_analysis.length} 道` : "核对题目与知识点",
          state: analysis && confirmedCount === analysis.question_analysis.length ? "done" : analysis ? "active" : "idle",
        },
        {
          label: "讲评报告",
          detail: lessonDownloadUrl ? "最近报告可下载" : "导出 Word 讲评材料",
          state: lessonDownloadUrl ? "done" : analysis ? "active" : "idle",
        },
      ];

  return (
    <main id="main-body" className={adminMode ? "admin-page" : "customer-page"}>
      {!adminMode ? <BackgroundCanvas /> : null}
      <ProductNav
        mode={adminMode ? "admin" : "teacher"}
        readiness={readiness}
        activeSection={activeSection}
        calibration={calibrationNavState}
      />
      <header className={adminMode ? "site-header admin-header" : "teacher-hero"}>
        <div className="hero-copy">
          <p className="eyebrow">{adminMode ? "运营与维护" : "Campus智能讲评"}</p>
          <h1>{adminMode ? "管理后台" : <>从试卷到讲评，<br />一次完成</>}</h1>
          {!adminMode ? (
            <React.Fragment>
              <p className="hero-subtitle">
                导入 Word 试卷与成绩表，系统自动整理题目、分析失分，并生成可编辑的课堂讲评报告。
              </p>
              <div className="hero-stats" aria-label="系统概览">
                <div className="hero-stat">
                  <strong>{readinessFacts?.paper_count ?? "--"}</strong>
                  <span>历史试卷</span>
                </div>
                <div className="hero-stat">
                  <strong>{readinessFacts?.question_count ?? "--"}</strong>
                  <span>题库资源</span>
                </div>
                <div className="hero-stat">
                  <strong>{readinessFacts?.knowledge_point_count ?? "--"}</strong>
                  <span>知识点库</span>
                </div>
              </div>
              <div className="hero-tags" aria-label="核心流程">
                <span>导入材料</span>
                <span>核对题目</span>
                <span>诊断学情</span>
                <span>生成报告</span>
              </div>
              <div className="hero-actions">
                <a className="button-link primary" href="#workspace">
                  开始使用
                </a>
              </div>
            </React.Fragment>
          ) : null}
        </div>
        {!adminMode ? (
          <HeroVisual
            examItems={examItems}
            facts={readinessFacts ?? null}
          />
        ) : (
          <>
            <nav aria-label="页面导航">
              <a href="#workspace">开始</a>
              <a href="#overview">概况</a>
              <a href="#review">确认</a>
              <a href="#questions">题目</a>
              <a href="#knowledge">知识点</a>
              <a href="#practice">练习</a>
              <a href="#student">学生</a>
              <a href="#audit">审核</a>
              <a href="#logs">日志</a>
              <a href="#report">报告</a>
            </nav>
            <IdentitySwitcher mode="admin" />
          </>
        )}
      </header>

      {error && <p className="notice danger">{error}</p>}
      {workflowMessage && !error && <p className="notice status">{workflowMessage}</p>}

      <section id="workspace" className="workspace">
        <div className="workspace-shell">
          <div className="workspace-main">
            <div className="section-heading">
              <p className="eyebrow">{adminMode ? "导入" : "开始"}</p>
              <h2>{adminMode ? "新建考试分析" : "上传课堂材料"}</h2>
            </div>

            {adminMode ? <ReleaseStrip readiness={readiness} /> : null}

            <div className="upload-grid">
              <FileInput
                accept=".docx"
                file={paperFile}
                label="Word 试卷"
                note="支持 .docx"
                onChange={setPaperFile}
              />
              <FileInput
                accept=".xlsx,.xlsm,.csv,.txt"
                file={scoreFile}
                label="成绩表"
                note="XLSX / CSV"
                onChange={setScoreFile}
              />
            </div>

            <div className="compact-form">
              <label>
                <span>考试编号</span>
                <input value={examId} onChange={(event) => setExamId(event.target.value)} />
              </label>
              <label>
                <span>班级名称</span>
                <input placeholder="可选" value={className} onChange={(event) => setClassName(event.target.value)} />
              </label>
              <div className="stage-field">
                <span>学段</span>
                <div className="mini-segmented" role="group" aria-label="学段">
                  <button
                    type="button"
                    className={stage === "senior_high" ? "active" : ""}
                    onClick={() => setStage("senior_high")}
                  >
                    高中
                  </button>
                  <button
                    type="button"
                    className={stage === "junior_high" ? "active" : ""}
                    onClick={() => setStage("junior_high")}
                  >
                    初中
                  </button>
                </div>
              </div>
            </div>

            <div className="actions">
              <button className="primary" onClick={() => void runAnalysis()} disabled={busy}>
                {busy ? "正在分析" : "开始分析"}
              </button>
              <a className="button-link" href={`${API_BASE}/api/p2/examples/scores`}>
                下载成绩表模板
              </a>
            </div>
          </div>

          <aside className="workspace-side" aria-label="分析进度">
            <div className="status-card">
              <div className="status-card-head">
                <div>
                  <span>{adminMode ? "本次分析" : "进度"}</span>
                  <strong>{analysis ? "报告材料已就绪" : adminMode ? "准备上传" : "准备开始"}</strong>
                </div>
                {adminMode ? (
                  <button className="text-button" onClick={() => void loadReadiness()}>
                    刷新
                  </button>
                ) : null}
              </div>
              <div className="workflow-steps">
                {workflowSteps.map((step) => (
                  <div key={step.label} className={`workflow-step ${step.state}`}>
                    <span className="step-dot" />
                    <div>
                      <strong>{step.label}</strong>
                      <small>{step.detail}</small>
                    </div>
                  </div>
                ))}
              </div>
              {adminMode && readiness?.components.length ? (
                <div className="readiness-list">
                  {readiness.components.map((item) => (
                    <div key={item.key} className={`readiness-item ${item.status}`}>
                      <span>{readinessText(item.status)}</span>
                      <div>
                        <strong>{item.name}</strong>
                        <small>{item.detail}</small>
                      </div>
                    </div>
                  ))}
                </div>
              ) : null}
            </div>

            {adminMode ? (
              <div className="system-facts">
                <div>
                  <strong>{readinessFacts?.paper_count ?? "--"}</strong>
                  <span>历史试卷</span>
                </div>
                <div>
                  <strong>{readinessFacts?.question_count ?? "--"}</strong>
                  <span>题库资源</span>
                </div>
                <div>
                  <strong>{readinessFacts?.knowledge_point_count ?? "--"}</strong>
                  <span>知识点库</span>
                </div>
                <div>
                  <strong>DOCX</strong>
                  <span>试卷格式</span>
                </div>
              </div>
            ) : (
              <div className="delivery-card" aria-label="分析交付内容">
                <header>
                  <strong>输出内容</strong>
                  <span>生成一份可继续编辑的讲评材料。</span>
                </header>
                <div>
                  <span className="delivery-icon" aria-hidden="true" />
                  <strong>题目整理</strong>
                  <em>题干、选项、表格、题图</em>
                </div>
                <div>
                  <span className="delivery-icon" aria-hidden="true" />
                  <strong>班级诊断</strong>
                  <em>得分率、失分点、知识点</em>
                </div>
                <div>
                  <span className="delivery-icon" aria-hidden="true" />
                  <strong>教师核对</strong>
                  <em>逐题确认后导出</em>
                </div>
                <div>
                  <span className="delivery-icon" aria-hidden="true" />
                  <strong>讲评报告</strong>
                  <em>Word 文档下载</em>
                </div>
              </div>
            )}

          </aside>

          {examItems.length ? (
            <div className="recent-exams workspace-recent">
              <div className="recent-exams-head">
                <span>{adminMode ? "最近考试" : "继续最近分析"}</span>
                <button className="text-button" onClick={() => void loadExamList()}>
                  刷新
                </button>
              </div>
              <div className="recent-exam-list">
                {examItems.slice(0, 3).map((item) => (
                  <article
                    key={item.exam_id}
                    className={activeExamId === item.exam_id ? "recent-exam active" : "recent-exam"}
                  >
                    <div className="recent-exam-main">
                      <div>
                        <strong>{item.name || item.exam_id}</strong>
                        <span>{examStatusText(item.status)}</span>
                      </div>
                      <div className="recent-exam-actions">
                        <button
                          className="text-button"
                          onClick={() => void openExam(item)}
                          disabled={busy || !item.question_count}
                        >
                          打开
                        </button>
                        <button
                          className="text-button danger-text"
                          onClick={() => void deleteExam(item)}
                          disabled={busy}
                          aria-label={`删除 ${item.name || item.exam_id}`}
                        >
                          删除
                        </button>
                      </div>
                    </div>
                    <p>
                      {item.question_count || 0} 题 · {fileTypesText(item.file_types) || "未上传"} · 教案{" "}
                      {item.lesson_plan_count} · 练习包 {item.practice_pack_count || 0}
                    </p>
                    {item.latest_lesson_plan?.file_name && <em>{item.latest_lesson_plan.file_name}</em>}
                  </article>
                ))}
              </div>
            </div>
          ) : null}
        </div>
      </section>

      {analysis ? (
        <>
      <section id="overview">
        <div className="section-heading">
          <p className="eyebrow">班级概况</p>
          <h2>考试概况</h2>
        </div>
        <div className="metric-grid">
          <Metric label="整体得分率" value={analysis ? pct(overall) : "--"} />
          <Metric label="题目数" value={analysis ? `${analysis.question_analysis.length}` : "--"} />
          <Metric label="重点讲评" value={`${countBySeverity(analysis, "critical")}`} />
          <Metric label="薄弱知识点" value={analysis ? `${weakKnowledge.length}` : "--"} />
          <Metric label="知识点覆盖率" value={analysis ? pct(tagCoverage) : "--"} />
          <Metric label="已确认" value={analysis ? `${confirmedCount}` : "--"} />
          {adminMode ? <Metric label="推荐题" value={analysis ? `${recommendationCount}` : "--"} /> : null}
        </div>
        {analysis?.teaching_report.summary && <p className="summary">{analysis.teaching_report.summary}</p>}
      </section>

      <section id="review">
        <div className="section-heading section-heading-action">
          <div>
            <p className="eyebrow">确认</p>
            <h2>核对题目</h2>
          </div>
          <button className="primary" onClick={() => void confirmAllQuestions()} disabled={!analysis || confirming}>
            {confirming ? "正在确认" : "一键确认全部"}
          </button>
        </div>
        <div className="review-panel">
          <div className="question-picker" aria-label="题目列表">
            {teacherQuestionList.map((item) => (
              <button
                key={item.question_no}
                className={item.question_no === selectedQuestionNo ? "active" : ""}
                onClick={() => selectQuestion(item.question_no)}
              >
                <span>第 {item.question_no} 题</span>
                <em>
                  {item.teacher_review_status === "confirmed"
                    ? "已确认"
                    : item.needs_review || item.warnings.length
                      ? "需复核"
                      : severityText[item.severity]}
                </em>
              </button>
            ))}
          </div>

          <div className="review-editor">
            {selectedQuestion && questionDraft ? (
              <>
                <div className="review-title">
                  <span className={`severity ${selectedQuestion.severity}`}>{severityText[selectedQuestion.severity]}</span>
                  <strong>第 {selectedQuestion.question_no} 题</strong>
                  <small>
                    均分 {formatScore(selectedQuestion.avg_score)} / 满分 {formatScore(selectedQuestion.full_score)}
                  </small>
                  {selectedQuestion.needs_review || selectedQuestion.warnings.length ? (
                    <small className="review-alert">需要复核</small>
                  ) : null}
                </div>

                {(selectedQuestion.needs_review || selectedQuestion.warnings.length) && (
                  <div className="question-warnings">
                    {(selectedQuestion.warnings.length ? selectedQuestion.warnings : ["解析置信度偏低，请核对题干、题图和知识点。"]).map(
                      (warning) => (
                        <span key={warning}>{warning}</span>
                      ),
                    )}
                    {typeof selectedQuestion.parse_confidence === "number" ? (
                      <span>解析置信度 {pct(selectedQuestion.parse_confidence)}</span>
                    ) : null}
                  </div>
                )}

                <div className="review-form">
                  <label>
                    <span>题号</span>
                    <input
                      value={questionDraft.question_no}
                      onChange={(event) =>
                        setQuestionDraft((current) =>
                          current ? { ...current, question_no: event.target.value } : current,
                        )
                      }
                    />
                  </label>
                  <label>
                    <span>题型</span>
                    <select
                      value={questionDraft.question_type}
                      onChange={(event) =>
                        setQuestionDraft((current) =>
                          current ? { ...current, question_type: event.target.value } : current,
                        )
                      }
                    >
                      <option value="">未设置</option>
                      <option value="single_choice">单选题</option>
                      <option value="multiple_choice">多选题</option>
                      <option value="blank">填空题</option>
                      <option value="solution">解答题</option>
                    </select>
                  </label>
                  <label>
                    <span>满分</span>
                    <input
                      inputMode="decimal"
                      value={questionDraft.full_score}
                      onChange={(event) =>
                        setQuestionDraft((current) =>
                          current ? { ...current, full_score: event.target.value } : current,
                        )
                      }
                    />
                  </label>
                </div>

                <div className="stem-editor-shell">
                  <div className="stem-editor-head">
                    <span>题干</span>
                    <button type="button" className="text-button" onClick={() => setStemRawEditing((value) => !value)}>
                      {stemRawEditing ? "查看排版" : "编辑原文"}
                    </button>
                  </div>
                  {stemRawEditing ? (
                    <textarea
                      className="stem-raw-textarea"
                      value={questionDraft.stem_text}
                      onChange={(event) =>
                        setQuestionDraft((current) => (current ? { ...current, stem_text: event.target.value } : current))
                      }
                    />
                  ) : (
                    <QuestionStemRenderer
                      text={questionDraft.stem_text}
                      images={stemImages(parseQuestionImages(questionDraft.image_text))}
                      onClick={() => setStemRawEditing(true)}
                    />
                  )}
                </div>

                {(parseQuestionOptions(questionDraft.option_text).length > 0 ||
                  ["single_choice", "multiple_choice"].includes(questionDraft.question_type)) ? (
                  <div className="stem-editor-shell option-editor-shell">
                    <div className="stem-editor-head">
                      <span>选项</span>
                      <button type="button" className="text-button" onClick={() => setOptionRawEditing((value) => !value)}>
                        {optionRawEditing ? "查看排版" : "编辑原文"}
                      </button>
                    </div>
                    {optionRawEditing ? (
                      <textarea
                        className="stem-raw-textarea option-raw-textarea"
                        value={questionDraft.option_text}
                        placeholder="每行一个选项，例如：A | 选项内容"
                        onChange={(event) =>
                          setQuestionDraft((current) =>
                            current ? { ...current, option_text: event.target.value } : current,
                          )
                        }
                      />
                    ) : (
                      <QuestionOptionsRenderer
                        options={parseQuestionOptions(questionDraft.option_text)}
                        images={parseQuestionImages(questionDraft.image_text)}
                        onClick={() => setOptionRawEditing(true)}
                      />
                    )}
                  </div>
                ) : null}

                <details className="image-editor-details">
                  <summary>题图确认</summary>
                  {(selectedQuestion.images?.length || parseQuestionImages(questionDraft.image_text).length) ? (
                    <div className="question-image-gallery" aria-label="题图预览">
                      {parseQuestionImages(questionDraft.image_text).map((image) => (
                        <figure key={`${image.image_id}-${image.path}`}>
                          <img src={questionImageUrl(image.path)} alt={image.image_id || "题图"} />
                          <figcaption>{image.role || "题图"}</figcaption>
                        </figure>
                      ))}
                    </div>
                  ) : (
                    <p className="section-note">当前题目没有识别到题图。</p>
                  )}
                  <label className="stacked-field">
                    <span>题图归属</span>
                    <textarea
                      className="image-textarea"
                      value={questionDraft.image_text}
                      placeholder="每行一个题图：图片ID | 图片路径 | 用途，例如 stem / option:A"
                      onChange={(event) =>
                        setQuestionDraft((current) =>
                          current ? { ...current, image_text: event.target.value } : current,
                        )
                      }
                    />
                  </label>
                </details>

                <label className="stacked-field">
                  <span>知识点</span>
                  <textarea
                    value={questionDraft.knowledge_text}
                    onChange={(event) =>
                      setQuestionDraft((current) =>
                        current ? { ...current, knowledge_text: event.target.value } : current,
                      )
                    }
                  />
                </label>

                <div className="actions">
                  <button className="primary" onClick={() => void saveQuestionReview()}>
                    保存确认
                  </button>
                  <button onClick={resetQuestionDraft}>恢复当前题</button>
                </div>
              </>
            ) : (
              <p className="summary">载入考试后可逐题确认题干、题型、满分和知识点。</p>
            )}
          </div>
        </div>
      </section>

      <section id="questions">
        <details className="collapsible-section" open>
          <summary className="collapsible-summary">
            <div>
              <p className="eyebrow">逐题诊断</p>
              <h2>{questionFilter === "priority" ? "重点题目分析" : "逐题分析"}</h2>
              <span>{filteredQuestions.length} 道题 · 按得分率和讲评优先级展示</span>
            </div>
            <span className="collapse-chip" aria-hidden="true" />
          </summary>
          <div className="collapsible-content">
            <div className="segmented" role="group" aria-label="题目筛选">
              {filters.map((item) => (
                <button
                  key={item.key}
                  className={questionFilter === item.key ? "active" : ""}
                  onClick={() => setQuestionFilter(item.key)}
                >
                  {item.label}
                </button>
              ))}
            </div>
            {questionFilter === "priority" ? <p className="section-note">默认展示最需要优先讲评的题目，可切换查看全卷。</p> : null}
            <div className={questionFilter === "priority" ? "question-card-grid priority-grid" : "question-card-grid"}>
              {filteredQuestions.map((item) => (
                <article key={item.question_no} className={questionFilter === "priority" ? "question-card featured" : "question-card"}>
                  <div className="question-card-head">
                    <div>
                      <strong>第 {item.question_no} 题</strong>
                      <span>
                        {questionTypeText(item.question_type)} · 均分 {formatScore(item.avg_score)} / 满分 {formatScore(item.full_score)}
                      </span>
                    </div>
                    <div className="question-card-badges">
                      <span className={`severity ${item.severity}`}>{severityText[item.severity]}</span>
                      <span className={`review-state ${item.teacher_review_status === "confirmed" ? "confirmed" : "pending"}`}>
                        {item.teacher_review_status === "confirmed" ? "已确认" : "未确认"}
                      </span>
                    </div>
                  </div>
                  <QuestionStemRenderer
                    text={questionDisplayText(item) || "待补充题干"}
                    images={stemImages(item.images || [])}
                    compact={questionFilter !== "priority"}
                  />
                  <QuestionOptionsRenderer
                    options={item.options || []}
                    images={item.images || []}
                    compact={questionFilter !== "priority"}
                  />
                  <div className="question-card-meta">
                    <span>得分率 {pct(item.score_rate)} · 失分率 {pct(item.loss_rate)}</span>
                    <span>知识点：{knowledgeNames(item.confirmed_knowledge_points)}</span>
                  </div>
                  <button className="text-button" onClick={() => selectQuestion(item.question_no, true)}>
                    编辑确认
                  </button>
                </article>
              ))}
            </div>
            {!filteredQuestions.length ? <p className="summary">当前筛选下暂无题目，可切换到全部题目查看。</p> : null}
          </div>
        </details>
      </section>

      <section id="knowledge">
        <details className="collapsible-section" open>
          <summary className="collapsible-summary">
            <div>
              <p className="eyebrow">知识点</p>
              <h2>知识点诊断</h2>
              <span>{analysis?.knowledge_diagnostics.length ?? 0} 个知识点 · 由逐题得分率汇总</span>
            </div>
            <div className="summary-actions">
              <button
                className="primary calibration-summary-button"
                type="button"
                onClick={(event) => {
                  event.preventDefault();
                  event.stopPropagation();
                  void runAiKnowledgeCalibration();
                }}
                disabled={!analysis || !activeExamId || knowledgeTagging}
              >
                {knowledgeTagging ? "矫正中" : "智能矫正"}
              </button>
              <span className="collapse-chip" aria-hidden="true" />
            </div>
          </summary>
          <div className="collapsible-content">
            {!adminMode ? (
              <div className={`calibration-guide ${calibrationStatus}`}>
                <span className="calibration-guide-orb" aria-hidden="true" />
                <div>
                  <strong>{knowledgeTagging ? "正在矫正整套试卷" : "建议矫正整套试卷"}</strong>
                  <span>
                    {knowledgeTagging
                      ? `${calibrationMessage || "模型正在比对题干语义与知识点库"} · ${formatDuration(calibrationElapsedSeconds)}`
                      : `系统会逐题矫正 ${calibrationTargetCount || "全部"} 道题的知识点，完成后推荐练习会同步刷新。`}
                  </span>
                </div>
                <button
                  className="primary"
                  type="button"
                  onClick={() => void runAiKnowledgeCalibration()}
                  disabled={!analysis || !activeExamId || knowledgeTagging}
                >
                  {knowledgeTagging ? "正在处理" : "开始智能矫正"}
                </button>
              </div>
            ) : null}
            <div className="knowledge-card-grid">
              {visibleKnowledgeDiagnostics.map((item) => (
                <article key={item.code} className="knowledge-card">
                  <div className="knowledge-card-head">
                    <div>
                      <strong>{item.name}</strong>
                      <span>相关题号 {item.related_question_nos.join(", ") || "暂无题号"}</span>
                    </div>
                    <span className={`severity ${item.severity}`}>{severityText[item.severity]}</span>
                  </div>
                  <div className="score-bar" aria-label={`得分率 ${pct(item.score_rate)}，失分率 ${pct(item.loss_rate)}`}>
                    <span style={{ width: `${Math.max(3, Math.min(100, item.score_rate * 100))}%` }} />
                  </div>
                  <div className="knowledge-card-foot">
                    <strong>得分率 {pct(item.score_rate)}</strong>
                    <span>失分率 {pct(item.loss_rate)}</span>
                    <p>{item.suggestion}</p>
                  </div>
                </article>
              ))}
            </div>
            {extraKnowledgeDiagnostics.length ? (
              <details className="secondary-details">
                <summary>查看其余 {extraKnowledgeDiagnostics.length} 个知识点</summary>
                <div className="knowledge-card-grid compact-knowledge-grid">
                  {extraKnowledgeDiagnostics.map((item) => (
                    <article key={item.code} className="knowledge-card">
                      <div className="knowledge-card-head">
                        <div>
                          <strong>{item.name}</strong>
                          <span>相关题号 {item.related_question_nos.join(", ") || "暂无题号"}</span>
                        </div>
                        <span className={`severity ${item.severity}`}>{severityText[item.severity]}</span>
                      </div>
                      <div className="score-bar" aria-label={`得分率 ${pct(item.score_rate)}，失分率 ${pct(item.loss_rate)}`}>
                        <span style={{ width: `${Math.max(3, Math.min(100, item.score_rate * 100))}%` }} />
                      </div>
                      <div className="knowledge-card-foot">
                        <strong>得分率 {pct(item.score_rate)}</strong>
                        <span>失分率 {pct(item.loss_rate)}</span>
                      </div>
                    </article>
                  ))}
                </div>
              </details>
            ) : null}
          </div>
        </details>
      </section>

      <section id="practice">
        <details className="collapsible-section recommendation-section" open>
          <summary className="collapsible-summary">
            <div>
              <p className="eyebrow">推荐题目</p>
              <h2>按薄弱知识点推荐练习</h2>
              <span>{countRecommendations(analysis)} 道题 · 与知识点诊断自动绑定</span>
            </div>
            <span className="collapse-chip" aria-hidden="true" />
          </summary>
          <div className="collapsible-content">
        <div className="practice-actions">
          <button
            className="primary"
            onClick={() => void createPracticePackFromRecommendations()}
            disabled={!analysis || !activeExamId || busy || !countRecommendations(analysis)}
          >
            生成练习包
          </button>
          <span>{practicePacks.length ? `已生成 ${practicePacks.length} 个练习包` : "推荐题可整理为班级练习"}</span>
        </div>
        {practicePacks.length ? (
          <div className="practice-pack-list">
            {practicePacks.slice(0, 3).map((pack) => (
              <article key={pack.practice_pack_id} className="practice-pack-card">
                <div>
                  <strong>{pack.title}</strong>
                  <span>{pack.needs_p3_sync ? "已生成" : "已同步"}</span>
                </div>
                <p>
                  {pack.question_ids.length} 题 · {pack.knowledge_point_ids.length} 个知识点
                </p>
                {pack.message && <em>{pack.message}</em>}
              </article>
            ))}
          </div>
        ) : null}
        <div className="practice-grid">
          {(analysis?.practice_recommendations ?? []).map((group) => (
            <article className="practice-group" key={`${group.knowledge_point_code}-${group.knowledge_point_name}`}>
              <div className="practice-head">
                <div>
                  <span className={`severity ${group.severity}`}>{severityText[group.severity]}</span>
                  <h3>{group.knowledge_point_name}</h3>
                </div>
                <small>
                  失分率 {pct(group.loss_rate ?? 0)} · 关联题号 {group.related_question_nos.join(", ") || "暂无题号"}
                </small>
              </div>
              <div className="recommendation-list">
                {group.items.map((item) => {
                  const itemKey = recommendationKey(group, item);
                  const isEditing = editingRecommendationKey === itemKey && recommendationDraft;
                  return (
                    <details key={item.bank_question_id} className="recommendation-card">
                      <summary>
                        <span>{questionTypeText(item.question_type) || "练习题"}</span>
                        <strong>{htmlPreview(item.content_html) || item.bank_question_id}</strong>
                        <span className={`match-chip ${recommendationMatchLabel(group, item) === "精准匹配" ? "exact" : "soft"}`}>
                          {recommendationMatchLabel(group, item)}
                        </span>
                        <em>{difficultyLabel(item.difficulty)}</em>
                      </summary>
                      <div className="recommendation-binding">
                        <span>绑定知识点：{group.knowledge_point_name}</span>
                        <span>推荐依据：该知识点失分率 {pct(group.loss_rate ?? 0)}</span>
                        <span>关联原题：{group.related_question_nos.join(", ") || "暂无"}</span>
                      </div>
                      {adminMode ? <div className="recommendation-meta">{item.bank_question_id}</div> : null}
                      {isEditing ? (
                        <div className="recommendation-editor">
                          <label className="stacked-field">
                            <span>题目内容</span>
                            <textarea
                              value={recommendationDraft.content_text}
                              onChange={(event) =>
                                setRecommendationDraft((current) =>
                                  current ? { ...current, content_text: event.target.value } : current,
                                )
                              }
                            />
                          </label>
                          <div className="recommendation-editor-row">
                            <label className="stacked-field">
                              <span>题型</span>
                              <input
                                value={recommendationDraft.question_type}
                                onChange={(event) =>
                                  setRecommendationDraft((current) =>
                                    current ? { ...current, question_type: event.target.value } : current,
                                  )
                                }
                              />
                            </label>
                            <label className="stacked-field">
                              <span>难度</span>
                              <input
                                value={recommendationDraft.difficulty}
                                onChange={(event) =>
                                  setRecommendationDraft((current) =>
                                    current ? { ...current, difficulty: event.target.value } : current,
                                  )
                                }
                              />
                            </label>
                          </div>
                          <label className="stacked-field">
                            <span>答案</span>
                            <textarea
                              value={recommendationDraft.answer_text}
                              onChange={(event) =>
                                setRecommendationDraft((current) =>
                                  current ? { ...current, answer_text: event.target.value } : current,
                                )
                              }
                            />
                          </label>
                          <label className="stacked-field">
                            <span>解析</span>
                            <textarea
                              value={recommendationDraft.analysis_text}
                              onChange={(event) =>
                                setRecommendationDraft((current) =>
                                  current ? { ...current, analysis_text: event.target.value } : current,
                                )
                              }
                            />
                          </label>
                          <label className="stacked-field">
                            <span>推荐理由</span>
                            <textarea
                              value={recommendationDraft.recommend_reason}
                              onChange={(event) =>
                                setRecommendationDraft((current) =>
                                  current ? { ...current, recommend_reason: event.target.value } : current,
                                )
                              }
                            />
                          </label>
                          <div className="actions recommendation-edit-actions">
                            <button className="primary" type="button" onClick={() => void saveRecommendationEdit(group, item)}>
                              保存推荐题
                            </button>
                            <button type="button" onClick={cancelRecommendationEdit}>
                              取消
                            </button>
                          </div>
                        </div>
                      ) : (
                        <>
                          <div className="recommendation-content" dangerouslySetInnerHTML={{ __html: item.content_html }} />
                          {item.answer_html && (
                            <div className="recommendation-answer">
                              <span>答案</span>
                              <div dangerouslySetInnerHTML={{ __html: item.answer_html }} />
                            </div>
                          )}
                          {item.analysis_html && (
                            <div className="recommendation-answer">
                              <span>解析</span>
                              <div dangerouslySetInnerHTML={{ __html: item.analysis_html }} />
                            </div>
                          )}
                          {item.recommend_reason ? <p className="recommendation-reason">{item.recommend_reason}</p> : null}
                          <div className="recommendation-card-actions">
                            <button type="button" className="text-button" onClick={() => startRecommendationEdit(group, item)}>
                              编辑推荐题
                            </button>
                          </div>
                        </>
                      )}
                    </details>
                  );
                })}
                {!group.items.length && <p className="summary">题库暂缺同类题，后续可补充校本练习。</p>}
              </div>
            </article>
          ))}
          {analysis && !(analysis.practice_recommendations ?? []).length && (
            <p className="summary">当前诊断暂无需要推荐的薄弱练习。</p>
          )}
        </div>
          </div>
        </details>
      </section>
        </>
      ) : (
        <section className="empty-outcome" aria-label="准备开始">
          <div>
            <p className="eyebrow">准备开始</p>
            <h2>选择 Word 试卷和成绩表后即可开始</h2>
          </div>
          <p>完成分析后，可逐题核对并导出 Word 讲评报告。</p>
        </section>
      )}

      {adminMode ? (
        <section id="student">
        <div className="section-heading">
          <p className="eyebrow">学生端</p>
          <h2>学生练习体验</h2>
        </div>
        <div className="student-shell">
          <article className="student-launch">
            <div>
              <span>错题练习</span>
              <h3>识别、讲解、举一反三</h3>
            </div>
            <button className="primary" onClick={() => void runStudentPreview()} disabled={studentBusy}>
              {studentBusy ? "生成中" : "生成练习预览"}
            </button>
            <div className="student-timeline" aria-label="学生练习流程">
              <span>错题识别</span>
              <span>知识点定位</span>
              <span>引导讲解</span>
              <span>变式练习</span>
            </div>
          </article>

          {studentFlow ? (
            <div className="student-result-grid">
              <article className="student-card student-question">
                <div className="student-card-head">
                  <span>{studentFlow.questionType || "题目"}</span>
                  <em>{Math.round(studentFlow.parseConfidence * 100)}%</em>
                </div>
                <div dangerouslySetInnerHTML={{ __html: studentFlow.questionHtml }} />
              </article>

              <article className="student-card">
                <div className="student-card-head">
                  <span>知识点</span>
                  <em>{studentFlow.jobStatus}</em>
                </div>
                <div className="candidate-list">
                  {studentFlow.candidates.map((candidate) => (
                    <div key={candidate.knowledge_point_id} className="candidate-chip">
                      <strong>{candidate.knowledge_point_name}</strong>
                      <span>{Math.round(candidate.confidence * 100)}%</span>
                    </div>
                  ))}
                </div>
              </article>

              <article className="student-card">
                <div className="student-card-head">
                  <span>下一步讲解</span>
                  <em>Step {studentFlow.guided.step_index}</em>
                </div>
                <p>{studentFlow.guided.content}</p>
              </article>

              <article className="student-card student-variants">
                <div className="student-card-head">
                  <span>变式题</span>
                  <em>{studentFlow.variantSource}</em>
                </div>
                <div className="student-card-actions">
                  <button className="primary" onClick={() => void submitStudentVariantsForReview()} disabled={auditBusy}>
                    {auditBusy ? "送审中" : "提交审核"}
                  </button>
                  <button onClick={() => void loadGeneratedQuestionReviews()} disabled={auditBusy}>
                    刷新待审
                  </button>
                </div>
                <div className="student-variant-list">
                  {studentFlow.variants.map((variant, index) => (
                    <details key={variant.generated_question_id} className="student-variant">
                      <summary>
                        <span>变式 {index + 1}</span>
                        <em>难度 {Math.round(variant.difficulty * 100) / 100}</em>
                      </summary>
                      <div dangerouslySetInnerHTML={{ __html: variant.content_html }} />
                      <div className="recommendation-answer">
                        <span>答案</span>
                        <div dangerouslySetInnerHTML={{ __html: variant.answer_html }} />
                      </div>
                      <div className="recommendation-answer">
                        <span>解析</span>
                        <div dangerouslySetInnerHTML={{ __html: variant.analysis_html }} />
                      </div>
                    </details>
                  ))}
                </div>
              </article>
            </div>
          ) : (
            <div className="student-empty">
              <strong>等待生成学生侧预览</strong>
              <span>错题识别服务已就绪</span>
            </div>
          )}
        </div>
        </section>
      ) : null}

      {adminMode ? (
        <section id="audit">
        <div className="section-heading">
          <p className="eyebrow">题目审核</p>
          <h2>AI 题目审核</h2>
        </div>
        <div className="audit-toolbar">
          <button onClick={() => void loadGeneratedQuestionReviews()} disabled={auditBusy}>
            刷新待审题
          </button>
          <span>
            {generatedReviewItems.length ? `${generatedReviewItems.length} 道待审` : "暂无待审题"}
            {auditSource ? ` · ${auditSource === "p3-http" ? "线上队列" : "本地队列"}` : ""}
          </span>
        </div>
        {generatedReviewItems.length ? (
          <div className="audit-grid">
            {generatedReviewItems.slice(0, 6).map((item) => (
              <article key={item.generated_question_id} className="audit-card">
                <div className="audit-card-head">
                  <div>
                    <span>{item.question_type || "题目"}</span>
                    <strong>{htmlPreview(item.content_html, 72) || item.generated_question_id}</strong>
                  </div>
                  <em>难度 {Math.round(item.difficulty * 100) / 100}</em>
                </div>
                <div className="audit-content" dangerouslySetInnerHTML={{ __html: item.content_html }} />
                <details className="audit-detail">
                  <summary>答案与解析</summary>
                  <div dangerouslySetInnerHTML={{ __html: item.answer_html }} />
                  <div dangerouslySetInnerHTML={{ __html: item.analysis_html }} />
                </details>
                <div className="audit-meta">
                  <span>{item.knowledge_point_ids.join(" · ")}</span>
                  <small>{item.generated_question_id}</small>
                </div>
                <div className="audit-actions">
                  <button
                    className="primary"
                    onClick={() => void reviewGeneratedQuestion(item.generated_question_id, "approved")}
                    disabled={auditBusy}
                  >
                    通过入库
                  </button>
                  <button
                    onClick={() => void reviewGeneratedQuestion(item.generated_question_id, "rejected")}
                    disabled={auditBusy}
                  >
                    驳回
                  </button>
                </div>
              </article>
            ))}
          </div>
        ) : (
          <div className="audit-empty">
            <strong>等待教师审核</strong>
            <span>学生预览生成的变式题可提交到这里。</span>
          </div>
        )}
        </section>
      ) : null}

      {adminMode ? (
        <section id="logs">
        <div className="section-heading">
          <p className="eyebrow">审计日志</p>
          <h2>系统审计</h2>
        </div>
        <div className="log-toolbar">
          <button onClick={() => void loadAuditLogs()}>刷新日志</button>
          <span>{auditLogs.length ? `最近 ${auditLogs.length} 条` : "暂无日志"}</span>
        </div>
        {auditLogs.length ? (
          <div className="log-list">
            {auditLogs.slice(0, 12).map((item) => (
              <article key={item.id} className="log-item">
                <div className="log-time">{formatAuditTime(item.created_at)}</div>
                <div>
                  <strong>{auditEventText(item.event)}</strong>
                  <span>
                    {auditResourceText(item.resource_type)} · {item.resource_id}
                  </span>
                </div>
                <code>{JSON.stringify(item.payload)}</code>
              </article>
            ))}
          </div>
        ) : (
          <div className="log-empty">
            <strong>等待系统动作</strong>
            <span>解析、确认、审核和下载都会沉淀为审计日志。</span>
          </div>
        )}
        </section>
      ) : null}

      {analysis ? (
      <section id="report">
        <div className="section-heading">
          <p className="eyebrow">导出</p>
          <h2>讲评报告</h2>
        </div>
        <div className="actions">
          <button className="primary" onClick={() => void downloadReport("docx")} disabled={!analysis || downloading}>
            导出 Word
          </button>
          {adminMode ? (
            <button onClick={() => void downloadReport("markdown")} disabled={!analysis || downloading}>
              导出 Markdown
            </button>
          ) : null}
          {lessonDownloadUrl && (
            <a className="button-link" href={`${API_BASE}${lessonDownloadUrl}`}>
              下载最近教案
            </a>
          )}
        </div>
        {analysis ? (
          <article className="report-preview">
            <div className="report-preview-head">
              <div>
                <span>讲评材料</span>
                <strong>{analysis.teaching_report.title}</strong>
              </div>
              <em>{analysis.teaching_report.priority_question_nos.length} 道优先讲评题</em>
            </div>
            <p>{analysis.teaching_report.summary}</p>
            <details>
              <summary>查看完整正文</summary>
              <pre>{analysis.teaching_report.markdown || ""}</pre>
            </details>
          </article>
        ) : (
          <p className="summary">完成处理后，可导出 Word 讲评报告。</p>
        )}
      </section>
      ) : null}

      {analysis?.warnings.length ? (
        <section>
          <div className="section-heading">
            <p className="eyebrow">数据校验</p>
            <h2>数据校验</h2>
          </div>
          <ul className="warning-list">
            {analysis.warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        </section>
      ) : null}

      <footer>{adminMode ? "校园智能学情系统 · 管理后台" : "Campus 智能讲评 · 教师端"}</footer>
    </main>
  );
}

function StudentPracticeApp() {
  const [studentId, setStudentId] = React.useState(CLIENT_CONTEXT.studentId);
  const [items, setItems] = React.useState<StudentPracticeItem[]>([]);
  const [selectedId, setSelectedId] = React.useState("");
  const [answerText, setAnswerText] = React.useState("A");
  const [answerResult, setAnswerResult] = React.useState<StudentPracticeAnswerResult | null>(null);
  const [progress, setProgress] = React.useState<StudentPracticeProgress | null>(null);
  const [report, setReport] = React.useState<StudentPersonalReport | null>(null);
  const [history, setHistory] = React.useState<StudentPracticeHistory | null>(null);
  const [historyFilter, setHistoryFilter] = React.useState<"all" | "correct" | "wrong">("all");
  const [wrongFile, setWrongFile] = React.useState<File | null>(null);
  const [wrongQuestion, setWrongQuestion] = React.useState<StudentWrongQuestionDetail | null>(null);
  const [guidedExplanation, setGuidedExplanation] = React.useState<StudentGuidedExplanation | null>(null);
  const [source, setSource] = React.useState("");
  const [message, setMessage] = React.useState("");
  const [error, setError] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [wrongBusy, setWrongBusy] = React.useState(false);
  const [historyBusy, setHistoryBusy] = React.useState(false);

  const selected = items.find((item) => item.bank_question_id === selectedId) || items[0] || null;
  const weakMastery = [...(progress?.mastery ?? [])].sort((left, right) => left.mastery_rate - right.mastery_rate).slice(0, 4);
  const recentAnswers = progress?.recent_answers ?? [];
  const candidateIds = (wrongQuestion?.knowledge_candidates ?? []).map((item) => item.knowledge_point_id).filter(Boolean);
  const reportWeak = report?.mastery.weak ?? [];
  const reportActions = report?.next_actions ?? [];
  const historyItems = history?.items ?? [];

  React.useEffect(() => {
    void loadRecommendations();
  }, []);

  React.useEffect(() => {
    if (selected && selected.bank_question_id !== selectedId) {
      setSelectedId(selected.bank_question_id);
    }
  }, [selected, selectedId]);

  async function loadRecommendations() {
    const resolvedStudentId = studentId.trim() || CLIENT_CONTEXT.studentId;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const data = await apiStudentEnvelopeRequest<StudentPracticeRecommendationList>(
        `/student/practice/recommendations?student_id=${encodeURIComponent(resolvedStudentId)}&limit=6`,
        resolvedStudentId,
      );
      setItems(data.items);
      setSource(data.source);
      setSelectedId(data.items[0]?.bank_question_id || "");
      setAnswerResult(null);
      await loadProgress(resolvedStudentId, true);
      await loadReport(resolvedStudentId, true);
      await loadHistory(resolvedStudentId, historyFilter, true);
      setMessage(data.detail || `已加载 ${data.items.length} 道练习题。`);
    } catch (err) {
      setItems([]);
      setSource("");
      setError(err instanceof Error ? err.message : "练习题加载失败");
    } finally {
      setBusy(false);
    }
  }

  async function loadProgress(resolvedStudentId = studentId.trim() || CLIENT_CONTEXT.studentId, quiet = false) {
    try {
      const data = await apiStudentEnvelopeRequest<StudentPracticeProgress>(
        `/student/practice/progress?student_id=${encodeURIComponent(resolvedStudentId)}&recent_limit=6`,
        resolvedStudentId,
      );
      setProgress(data);
      if (data.detail && !quiet) setMessage(data.detail);
    } catch (err) {
      setProgress(null);
      if (!quiet) setError(err instanceof Error ? err.message : "学习进度加载失败");
    }
  }

  async function loadReport(resolvedStudentId = studentId.trim() || CLIENT_CONTEXT.studentId, quiet = false) {
    try {
      const data = await apiStudentEnvelopeRequest<StudentPersonalReport>(
        `/student/reports/personal?student_id=${encodeURIComponent(resolvedStudentId)}&recent_limit=6`,
        resolvedStudentId,
      );
      setReport(data);
      if (!quiet) setMessage("个人学习报告已更新。");
    } catch (err) {
      setReport(null);
      if (!quiet) setError(err instanceof Error ? err.message : "个人学习报告加载失败");
    }
  }

  async function loadHistory(
    resolvedStudentId = studentId.trim() || CLIENT_CONTEXT.studentId,
    filter = historyFilter,
    quiet = false,
  ) {
    setHistoryBusy(true);
    try {
      const query = new URLSearchParams({
        student_id: resolvedStudentId,
        limit: "8",
        offset: "0",
      });
      if (filter === "correct") query.set("is_correct", "true");
      if (filter === "wrong") query.set("is_correct", "false");
      const data = await apiStudentEnvelopeRequest<StudentPracticeHistory>(
        `/student/practice/history?${query.toString()}`,
        resolvedStudentId,
      );
      setHistory(data);
      if (data.detail && !quiet) setMessage(data.detail);
    } catch (err) {
      setHistory(null);
      if (!quiet) setError(err instanceof Error ? err.message : "练习历史加载失败");
    } finally {
      setHistoryBusy(false);
    }
  }

  async function uploadWrongQuestion() {
    if (!wrongFile) {
      setError("请先选择一张错题图片。");
      return;
    }
    const resolvedStudentId = studentId.trim() || CLIENT_CONTEXT.studentId;
    const formData = new FormData();
    formData.append("student_id", resolvedStudentId);
    formData.append("subject", "math");
    formData.append("grade", "8");
    formData.append("image", wrongFile);
    setWrongBusy(true);
    setError("");
    setGuidedExplanation(null);
    try {
      const result = await apiStudentEnvelopeRequest<StudentWrongQuestionUploadResult>(
        "/student/wrong-questions",
        resolvedStudentId,
        {
          method: "POST",
          headers: { "Idempotency-Key": `student-wrong-${wrongFile.name}-${wrongFile.size}-${Date.now()}` },
          body: formData,
        },
      );
      await loadWrongQuestion(result.wrong_question_id, resolvedStudentId, true);
      setMessage("错题已上传，识别结果已同步。");
    } catch (err) {
      setError(err instanceof Error ? err.message : "错题上传失败");
    } finally {
      setWrongBusy(false);
    }
  }

  async function loadWrongQuestion(wrongQuestionId: string, resolvedStudentId = studentId.trim() || CLIENT_CONTEXT.studentId, quiet = false) {
    try {
      const detail = await apiStudentEnvelopeRequest<StudentWrongQuestionDetail>(
        `/student/wrong-questions/${encodeURIComponent(wrongQuestionId)}?student_id=${encodeURIComponent(resolvedStudentId)}`,
        resolvedStudentId,
      );
      setWrongQuestion(detail);
      if (!quiet) setMessage(detail.status === "recognized" ? "识别完成，请确认知识点。" : `当前状态：${detail.status}`);
    } catch (err) {
      if (!quiet) setError(err instanceof Error ? err.message : "错题识别结果加载失败");
    }
  }

  async function confirmWrongQuestion() {
    if (!wrongQuestion) return;
    if (!candidateIds.length) {
      setError("暂无可确认的知识点候选。");
      return;
    }
    const resolvedStudentId = studentId.trim() || CLIENT_CONTEXT.studentId;
    setWrongBusy(true);
    setError("");
    try {
      await apiStudentEnvelopeRequest<{ wrong_question_id: string; status: string }>(
        `/student/wrong-questions/${encodeURIComponent(wrongQuestion.wrong_question_id)}/confirm?student_id=${encodeURIComponent(resolvedStudentId)}`,
        resolvedStudentId,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            stem_html: wrongQuestion.question.stem_html || `<p>${wrongQuestion.question.stem_text || ""}</p>`,
            question_type: wrongQuestion.question.question_type || "solution",
            knowledge_point_ids: candidateIds,
          }),
        },
      );
      await loadWrongQuestion(wrongQuestion.wrong_question_id, resolvedStudentId, true);
      setMessage("错题已确认，可以开始引导讲解。");
    } catch (err) {
      setError(err instanceof Error ? err.message : "错题确认失败");
    } finally {
      setWrongBusy(false);
    }
  }

  async function requestGuidedExplanation(mode = "hint") {
    if (!wrongQuestion) return;
    const resolvedStudentId = studentId.trim() || CLIENT_CONTEXT.studentId;
    setWrongBusy(true);
    setError("");
    try {
      const result = await apiStudentEnvelopeRequest<StudentGuidedExplanation>(
        `/student/wrong-questions/${encodeURIComponent(wrongQuestion.wrong_question_id)}/explanation/next?student_id=${encodeURIComponent(resolvedStudentId)}`,
        resolvedStudentId,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            current_step_index: guidedExplanation?.step_index ?? 0,
            student_input: "",
            mode,
          }),
        },
      );
      setGuidedExplanation(result);
      setMessage("已生成下一步讲解。");
    } catch (err) {
      setError(err instanceof Error ? err.message : "讲解生成失败");
    } finally {
      setWrongBusy(false);
    }
  }

  async function submitAnswer(isCorrect: boolean) {
    if (!selected) {
      setError("当前没有可提交的题目。");
      return;
    }
    const resolvedStudentId = studentId.trim() || CLIENT_CONTEXT.studentId;
    setBusy(true);
    setError("");
    try {
      const result = await apiStudentEnvelopeRequest<StudentPracticeAnswerResult>(
        "/student/practice/answers",
        resolvedStudentId,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Idempotency-Key": `student-ui-${selected.bank_question_id}-${Date.now()}`,
          },
          body: JSON.stringify({
            student_id: resolvedStudentId,
            bank_question_id: selected.bank_question_id,
            answer_text: answerText,
            is_correct: isCorrect,
            used_seconds: 42,
          }),
        },
      );
      setAnswerResult(result);
      await loadProgress(resolvedStudentId, true);
      await loadReport(resolvedStudentId, true);
      await loadHistory(resolvedStudentId, historyFilter, true);
      setMessage(result.detail || "作答已保存。");
    } catch (err) {
      setAnswerResult(null);
      setError(err instanceof Error ? err.message : "作答提交失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="student-page">
      <ProductNav mode="student" studentId={studentId} />
      <header className="student-hero">
        <div>
          <p className="eyebrow">学生练习</p>
          <h1>学生练习</h1>
        </div>
        <div className="student-identity">
          <label>
            <span>学生</span>
            <input value={studentId} onChange={(event) => setStudentId(event.target.value)} />
          </label>
          <button className="primary" onClick={() => void loadRecommendations()} disabled={busy}>
            {busy ? "加载中" : "刷新"}
          </button>
          <a className="button-link" href={`/?apiBase=${encodeURIComponent(API_BASE)}`}>
            教师端
          </a>
          <IdentitySwitcher mode="student" displayStudentId={studentId} />
        </div>
      </header>

      {(message || error) && (
        <div className={error ? "alert error" : "alert"}>{error || message}</div>
      )}

      <section className="student-report-shell" aria-label="个人学习报告">
        <article className="student-report-card primary-report">
          <div className="student-card-head">
            <span>个人学习报告</span>
            <em>{report?.source === "p3-http" ? "实时画像" : "等待同步"}</em>
          </div>
          <div className="student-report-score">
            <strong>{report ? studentReportLevelText(report.summary.report_level) : "等待数据"}</strong>
            <span>
              {report
                ? `正确率 ${pct(report.summary.accuracy_rate)} · 平均掌握度 ${pct(report.summary.average_mastery_rate)}`
                : "刷新后生成学生学习画像"}
            </span>
          </div>
          <div className="student-report-metrics">
            <div>
              <span>累计作答</span>
              <strong>{report?.summary.answer_count ?? 0}</strong>
            </div>
            <div>
              <span>错题</span>
              <strong>{report?.summary.wrong_question_count ?? 0}</strong>
            </div>
            <div>
              <span>待强化</span>
              <strong>{reportWeak.length}</strong>
            </div>
          </div>
          <button onClick={() => void loadReport()} disabled={busy || wrongBusy}>
            刷新报告
          </button>
        </article>

        <article className="student-report-card">
          <div className="student-panel-head">
            <span>薄弱知识点</span>
            <strong>{reportWeak.length} 项</strong>
          </div>
          {reportWeak.length ? (
            <div className="student-report-list">
              {reportWeak.slice(0, 4).map((item) => (
                <div key={item.knowledge_point_id} className="student-report-row">
                  <span>{item.knowledge_point_name || item.knowledge_point_id}</span>
                  <strong>{pct(item.mastery_rate)}</strong>
                </div>
              ))}
            </div>
          ) : (
            <p className="student-muted">完成练习或确认错题后，系统会给出薄弱项。</p>
          )}
        </article>

        <article className="student-report-card">
          <div className="student-panel-head">
            <span>下一步建议</span>
            <strong>{reportActions.length} 条</strong>
          </div>
          {reportActions.length ? (
            <div className="student-action-list">
              {reportActions.map((action) => (
                <div key={`${action.action_type}-${action.priority}`} className={`student-action ${action.priority}`}>
                  <strong>{studentActionText(action.action_type)}</strong>
                  <span>{action.knowledge_point_ids.slice(0, 2).join(" · ") || action.priority}</span>
                </div>
              ))}
            </div>
          ) : (
            <p className="student-muted">暂无建议，先刷新推荐题或上传错题。</p>
          )}
        </article>
      </section>

      <section className="student-wrong-shell" aria-label="错题识别">
        <article className="student-wrong-card">
          <div className="student-card-head">
            <span>错题识别</span>
            <em>{wrongQuestion?.status || "未上传"}</em>
          </div>
          <FileInput
            accept="image/png,image/jpeg,image/webp"
            file={wrongFile}
            label="上传错题图片"
            note="支持 PNG / JPG / WebP，识别后可确认知识点"
            onChange={setWrongFile}
          />
          <div className="student-submit-row">
            <button onClick={() => void uploadWrongQuestion()} disabled={wrongBusy || !wrongFile}>
              {wrongBusy ? "处理中" : "上传识别"}
            </button>
            <button
              onClick={() => wrongQuestion && void loadWrongQuestion(wrongQuestion.wrong_question_id)}
              disabled={wrongBusy || !wrongQuestion}
            >
              刷新识别
            </button>
          </div>
        </article>

        {wrongQuestion ? (
          <article className="student-wrong-card">
            <div className="student-card-head">
              <span>{wrongQuestion.question.question_type || "识别题目"}</span>
              <em>{wrongQuestion.wrong_question_id}</em>
            </div>
            <div
              className="student-question-body"
              dangerouslySetInnerHTML={{
                __html: wrongQuestion.question.stem_html || `<p>${wrongQuestion.question.stem_text || "等待识别结果"}</p>`,
              }}
            />
            <div className="student-candidate-list">
              {wrongQuestion.knowledge_candidates.length ? (
                wrongQuestion.knowledge_candidates.map((candidate) => (
                  <div key={candidate.knowledge_point_id} className="student-candidate">
                    <strong>{candidate.knowledge_point_name || candidate.knowledge_point_id}</strong>
                    <span>{candidate.confidence ? pct(candidate.confidence) : "置信度未返回"}</span>
                    {candidate.reason ? <em>{candidate.reason}</em> : null}
                  </div>
                ))
              ) : (
                <p className="student-muted">暂无知识点候选。</p>
              )}
            </div>
            <div className="student-submit-row">
              <button
                className="primary"
                onClick={() => void confirmWrongQuestion()}
                disabled={wrongBusy || !candidateIds.length || !["recognized", "confirmed"].includes(wrongQuestion.status)}
              >
                确认知识点
              </button>
              <button
                onClick={() => void requestGuidedExplanation("hint")}
                disabled={wrongBusy || !["confirmed", "learning"].includes(wrongQuestion.status)}
              >
                下一步提示
              </button>
              <button
                onClick={() => void requestGuidedExplanation("summary")}
                disabled={wrongBusy || !["confirmed", "learning"].includes(wrongQuestion.status)}
              >
                总结思路
              </button>
            </div>
            {guidedExplanation ? (
              <div className="student-guidance">
                <span>Step {guidedExplanation.step_index}</span>
                <p>{guidedExplanation.content}</p>
              </div>
            ) : null}
          </article>
        ) : null}
      </section>

      <section className="student-progress-shell" aria-label="学习进度">
        <div className="student-progress-cards">
          <article>
            <span>累计作答</span>
            <strong>{progress?.answer_count ?? 0}</strong>
            <em>{progress ? `${progress.correct_count} 题正确` : "等待同步"}</em>
          </article>
          <article>
            <span>正确率</span>
            <strong>{progress ? pct(progress.accuracy_rate) : "--"}</strong>
            <em>{progress?.source === "p3-http" ? "实时同步" : "本地记录"}</em>
          </article>
          <article>
            <span>知识点</span>
            <strong>{progress?.mastery_count ?? 0}</strong>
            <em>按掌握度排序</em>
          </article>
        </div>
        <div className="student-progress-detail">
          <article>
            <div className="student-panel-head">
              <span>薄弱知识点</span>
              <strong>{weakMastery.length} 项</strong>
            </div>
            {weakMastery.length ? (
              <div className="student-mastery-list">
                {weakMastery.map((item) => (
                  <div key={item.knowledge_point_id} className="student-mastery-row">
                    <span>{item.knowledge_point_name || item.knowledge_point_id}</span>
                    <strong>{pct(item.mastery_rate)}</strong>
                  </div>
                ))}
              </div>
            ) : (
              <p className="student-muted">完成一次练习后生成掌握度。</p>
            )}
          </article>
          <article>
            <div className="student-panel-head">
              <span>最近作答</span>
              <strong>{recentAnswers.length} 条</strong>
            </div>
            {recentAnswers.length ? (
              <div className="student-recent-list">
                {recentAnswers.map((item) => (
                  <div key={item.answer_record_id} className={item.is_correct ? "student-recent-row correct" : "student-recent-row"}>
                    <span>{item.bank_question_id}</span>
                    <strong>{item.is_correct ? "正确" : "待巩固"}</strong>
                    <em>{item.answer_text || "未填答案"} · {item.used_seconds}s</em>
                  </div>
                ))}
              </div>
            ) : (
              <p className="student-muted">暂无作答记录。</p>
            )}
          </article>
        </div>
      </section>

      <section className="student-history-shell" aria-label="练习历史">
        <div className="student-history-head">
          <div>
            <span>练习历史</span>
            <strong>{history?.total_count ?? 0} 条记录</strong>
          </div>
          <div className="student-history-actions">
            {[
              ["all", "全部"],
              ["correct", "正确"],
              ["wrong", "待订正"],
            ].map(([key, label]) => (
              <button
                key={key}
                className={historyFilter === key ? "active" : ""}
                onClick={() => {
                  const nextFilter = key as "all" | "correct" | "wrong";
                  setHistoryFilter(nextFilter);
                  void loadHistory(undefined, nextFilter);
                }}
                disabled={historyBusy}
              >
                {label}
              </button>
            ))}
            <button onClick={() => void loadHistory()} disabled={historyBusy}>
              {historyBusy ? "同步中" : "刷新历史"}
            </button>
          </div>
        </div>
        {historyItems.length ? (
          <div className="student-history-list">
            {historyItems.map((item) => (
              <article key={item.answer_record_id} className={item.is_correct ? "student-history-row correct" : "student-history-row"}>
                <div>
                  <span>{item.bank_question_id}</span>
                  <strong>{item.content_preview || item.question_type}</strong>
                  <em>{item.knowledge_point_ids.slice(0, 3).join(" · ") || "未绑定知识点"}</em>
                </div>
                <div>
                  <strong>{item.is_correct ? "正确" : "待订正"}</strong>
                  <span>{item.answer_text || "未填写"} · {item.used_seconds}s</span>
                </div>
              </article>
            ))}
          </div>
        ) : (
          <p className="student-muted">暂无历史记录，完成一次推荐练习后会自动同步。</p>
        )}
      </section>

      <section className="student-practice-layout">
        <aside className="student-practice-list">
          <div className="student-panel-head">
            <span>{source === "p3-http" ? "题库推荐" : "本地推荐"}</span>
            <strong>{items.length} 题</strong>
          </div>
          {items.length ? (
            items.map((item, index) => (
              <button
                key={item.bank_question_id}
                className={`student-practice-item ${item.bank_question_id === selected?.bank_question_id ? "active" : ""}`}
                onClick={() => {
                  setSelectedId(item.bank_question_id);
                  setAnswerResult(null);
                }}
              >
                <span>练习 {index + 1}</span>
                <strong>{htmlPreview(item.content_html, 54) || item.bank_question_id}</strong>
                <em>难度 {Math.round(item.difficulty * 100)}%</em>
              </button>
            ))
          ) : (
            <div className="student-list-empty">暂无推荐题</div>
          )}
        </aside>

        <article className="student-practice-card">
          {selected ? (
            <>
              <div className="student-card-head">
                <span>{selected.question_type || "练习题"}</span>
                <em>{selected.bank_question_id}</em>
              </div>
              <div className="student-question-body" dangerouslySetInnerHTML={{ __html: selected.content_html }} />
              <div className="student-reason">
                <span>推荐依据</span>
                <p>{selected.recommend_reason}</p>
              </div>
              <div className="student-answer-row">
                {["A", "B", "C", "D"].map((option) => (
                  <button
                    key={option}
                    className={answerText === option ? "active" : ""}
                    onClick={() => setAnswerText(option)}
                  >
                    {option}
                  </button>
                ))}
              </div>
              <div className="student-submit-row">
                <button onClick={() => void submitAnswer(false)} disabled={busy}>
                  标记错题
                </button>
                <button className="primary" onClick={() => void submitAnswer(true)} disabled={busy}>
                  提交正确
                </button>
              </div>
              {answerResult && (
                <div className="student-answer-result">
                  <div>
                    <span>记录</span>
                    <strong>{answerResult.answer_record_id}</strong>
                  </div>
                  {answerResult.updated_mastery.length ? (
                    <div className="mastery-grid">
                      {answerResult.updated_mastery.map((item) => (
                        <div key={item.knowledge_point_id} className="mastery-chip">
                          <span>{item.knowledge_point_name || item.knowledge_point_id}</span>
                          <strong>{pct(item.mastery_rate)}</strong>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p>{answerResult.source === "p3-http" ? "本次作答未产生掌握度变化。" : "题库服务暂不可用，本地仅返回作答回执。"}</p>
                  )}
                </div>
              )}
            </>
          ) : (
            <div className="student-empty">
              <strong>等待推荐题</strong>
              <span>刷新后显示学生练习。</span>
            </div>
          )}
        </article>
      </section>

      <footer>校园智能学情系统 · 学生端</footer>
    </main>
  );
}

function FileInput({
  accept,
  file,
  label,
  note,
  onChange,
}: {
  accept: string;
  file: File | null;
  label: string;
  note: string;
  onChange: (file: File | null) => void;
}) {
  return (
    <label className="upload-box">
      <input accept={accept} type="file" onChange={(event) => onChange(event.target.files?.[0] ?? null)} />
      <span>{label}</span>
      <strong>{file?.name || "点击选择文件"}</strong>
      <em>{note}</em>
    </label>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

/* Math/science decorative motifs: floating formulas, geometric shapes, symbols.
 * All positions are normalized to 0-100 of viewport and use vw/vh + absolute positioning.
 */
const FORMULA_TOKENS = [
  { text: "a² + b² = c²",        size: 22, x: 6,  y: 14, color: "var(--brand)",      drift: 26, delay: 0   },
  { text: "e^(iπ) + 1 = 0",      size: 28, x: 78, y: 24, color: "var(--brand-bright)", drift: 32, delay: 4   },
  { text: "∫ f(x) dx",           size: 32, x: 14, y: 62, color: "var(--brand)",      drift: 28, delay: 8   },
  { text: "Σᵢ₌₁ⁿ xᵢ",            size: 26, x: 60, y: 78, color: "var(--brand-bright)", drift: 30, delay: 2   },
  { text: "sin²θ + cos²θ = 1",   size: 18, x: 30, y: 38, color: "var(--ink-3)",      drift: 24, delay: 6   },
  { text: "f(x) = ax + b",       size: 22, x: 86, y: 60, color: "var(--brand)",      drift: 34, delay: 12  },
  { text: "∇ · E = ρ/ε₀",        size: 24, x: 22, y: 84, color: "var(--brand-bright)", drift: 28, delay: 10  },
  { text: "lim n→∞",             size: 20, x: 50, y: 12, color: "var(--ink-3)",      drift: 22, delay: 14  },
  { text: "π ≈ 3.14159",          size: 18, x: 70, y: 46, color: "var(--brand)",      drift: 26, delay: 16  },
  { text: "dy/dx",               size: 26, x: 38, y: 70, color: "var(--brand-bright)", drift: 30, delay: 18  },
  { text: "E = mc²",              size: 24, x: 4,  y: 50, color: "var(--brand)",      drift: 28, delay: 1   },
  { text: "∞",                   size: 64, x: 92, y: 8,  color: "var(--brand-soft-2)", drift: 40, delay: 5   },
  { text: "∀ x ∈ ℝ",              size: 20, x: 6,  y: 86, color: "var(--ink-3)",      drift: 24, delay: 7   },
  { text: "P(A|B) = P(B|A)P(A) / P(B)", size: 14, x: 44, y: 90, color: "var(--ink-3)", drift: 20, delay: 9 },
  { text: "Δx → 0",              size: 22, x: 84, y: 86, color: "var(--brand)",      drift: 26, delay: 11  },
];

const GEOMETRY_TOKENS = [
  { shape: "hex",      x: 12, y: 18, size: 60, rotate: -6,  drift: 36, delay: 0 },
  { shape: "circle",   x: 88, y: 28, size: 48, rotate: 0,   drift: 32, delay: 6 },
  { shape: "pentagon", x: 8,  y: 78, size: 52, rotate: 0,   drift: 40, delay: 12 },
  { shape: "diamond",  x: 90, y: 80, size: 40, rotate: 28,  drift: 30, delay: 4 },
];

const PARTICLE_FIELD = [
  { x:  4,  y:  8,  r: 1.6, kind: "bright" },
  { x:  9,  y: 32,  r: 1.2, kind: "dim" },
  { x: 14,  y: 70,  r: 1.8, kind: "bright" },
  { x: 22,  y: 18,  r: 1.0, kind: "dim" },
  { x: 28,  y: 88,  r: 1.6, kind: "bright" },
  { x: 33,  y: 44,  r: 1.4, kind: "dim" },
  { x: 40,  y: 12,  r: 1.8, kind: "bright" },
  { x: 46,  y: 76,  r: 1.2, kind: "dim" },
  { x: 52,  y: 28,  r: 1.6, kind: "bright" },
  { x: 58,  y: 60,  r: 1.0, kind: "dim" },
  { x: 63,  y:  6,  r: 1.6, kind: "bright" },
  { x: 68,  y: 92,  r: 1.4, kind: "dim" },
  { x: 74,  y: 38,  r: 1.8, kind: "bright" },
  { x: 81,  y: 14,  r: 1.2, kind: "dim" },
  { x: 86,  y: 64,  r: 1.6, kind: "bright" },
  { x: 92,  y: 30,  r: 1.4, kind: "dim" },
  { x: 96,  y: 82,  r: 1.6, kind: "bright" },
  { x: 18,  y: 54,  r: 1.0, kind: "dim" },
  { x: 50,  y: 48,  r: 1.4, kind: "dim" },
  { x: 78,  y: 50,  r: 1.2, kind: "dim" },
];

type ShapeKind = "triangle" | "hex" | "circle" | "square" | "diamond" | "pentagon";

function shapePath(shape: ShapeKind, size: number): string {
  const r = size / 2;
  const cx = 0, cy = 0;
  switch (shape) {
    case "triangle":
      return `M 0 ${-r} L ${r * 0.866} ${r * 0.5} L ${-r * 0.866} ${r * 0.5} Z`;
    case "hex":
      return [0, 60, 120, 180, 240, 300]
        .map((deg) => {
          const rad = (deg * Math.PI) / 180;
          return `${cx + r * Math.cos(rad)} ${cy + r * Math.sin(rad)}`;
        })
        .map((p, i) => (i === 0 ? `M ${p}` : `L ${p}`))
        .join(" ") + " Z";
    case "circle":
      return `M ${r} 0 A ${r} ${r} 0 1 1 ${-r} 0 A ${r} ${r} 0 1 1 ${r} 0 Z`;
    case "square":
      return `M ${-r} ${-r} L ${r} ${-r} L ${r} ${r} L ${-r} ${r} Z`;
    case "diamond":
      return `M 0 ${-r} L ${r} 0 L 0 ${r} L ${-r} 0 Z`;
    case "pentagon":
      return [0, 72, 144, 216, 288]
        .map((deg) => {
          const rad = ((deg - 90) * Math.PI) / 180;
          return `${cx + r * Math.cos(rad)} ${cy + r * Math.sin(rad)}`;
        })
        .map((p, i) => (i === 0 ? `M ${p}` : `L ${p}`))
        .join(" ") + " Z";
  }
}

function BackgroundCanvas() {
  const canvasRef = React.useRef<HTMLDivElement | null>(null);
  const burstRefs = React.useRef<Array<SVGCircleElement | null>>([]);
  const [scrollY, setScrollY] = React.useState(0);
  const [docHeight, setDocHeight] = React.useState(1);
  const [mouse, setMouse] = React.useState({ x: 0.5, y: 0.5 });

  React.useEffect(() => {
    const update = () => {
      const h = document.documentElement.scrollHeight - window.innerHeight;
      setScrollY(window.scrollY);
      setDocHeight(Math.max(1, h));
    };
    update();
    window.addEventListener("scroll", update, { passive: true });
    window.addEventListener("resize", update);
    return () => {
      window.removeEventListener("scroll", update);
      window.removeEventListener("resize", update);
    };
  }, []);

  React.useEffect(() => {
    const onMove = (e: PointerEvent) => {
      setMouse({
        x: e.clientX / window.innerWidth,
        y: e.clientY / window.innerHeight,
      });
    };
    window.addEventListener("pointermove", onMove, { passive: true });
    return () => window.removeEventListener("pointermove", onMove);
  }, []);

  // Section enter/exit observer.
  // Strategy:
  //  • Each section plays its randomly-chosen entry animation EXACTLY ONCE
  //    — the very first time it intersects the viewport. After that, the
  //    section simply stays visible (.in-view stays on). Subsequent up/down
  //    scrolls never replay the animation, so the page feels stable.
  //  • The "already played" state is persisted in sessionStorage so HMR /
  //    page reload during development doesn't replay on first scroll-in.
  //  • The class is still added in a rAF so the add + reflow happen in one
  //    paint tick (defends against the "stuck mid-frame" bug).
  //  • Hero/header sections at the very top of the page are auto-marked
  //    on mount so they don't animate on the initial page load.
  React.useEffect(() => {
    const sections = Array.from(document.querySelectorAll("section, .teacher-hero")) as HTMLElement[];
    const ENTRY_FX = [
      "fx-particles",
      "fx-flip",
      "fx-blur-rise",
      "fx-slide-left",
      "fx-slide-right",
      "fx-zoom",
      "fx-rotate-in",
      "fx-stagger-grid",
    ];
    const chooseFx = () => ENTRY_FX[(Math.random() * ENTRY_FX.length) | 0];
    const SEEN_KEY = "cd.replayedEntrySet.v1";

    const loadSeen = (): Set<string> => {
      try {
        const raw = sessionStorage.getItem(SEEN_KEY);
        return new Set(raw ? (JSON.parse(raw) as string[]) : []);
      } catch {
        return new Set();
      }
    };
    const saveSeen = (set: Set<string>) => {
      try {
        sessionStorage.setItem(SEEN_KEY, JSON.stringify(Array.from(set)));
      } catch {
        /* ignore quota errors */
      }
    };

    const seen = loadSeen();
    const identity = (el: HTMLElement) =>
      el.getAttribute("data-section-idx") || el.id || el.className || "anon";

    // Sections already visible on mount (e.g. the page hero) shouldn't animate
    // either — mark them as already-seen immediately.
    sections.forEach((el) => {
      const rect = el.getBoundingClientRect();
      const inViewport = rect.top < window.innerHeight && rect.bottom > 0;
      if (inViewport) seen.add(identity(el));
    });
    saveSeen(seen);

    const playEntry = (el: HTMLElement) => {
      const key = identity(el);
      if (seen.has(key)) {
        // Already played: just keep it visible, no animation.
        requestAnimationFrame(() => {
          el.classList.remove(...ENTRY_FX);
          el.classList.add("in-view", "entry-played");
        });
        return;
      }
      seen.add(key);
      saveSeen(seen);

      requestAnimationFrame(() => {
        el.classList.remove("in-view", "entry-played", ...ENTRY_FX);
        void el.offsetWidth;
        el.classList.add(chooseFx());
        el.classList.add("in-view");
      });
    };

    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          const el = entry.target as HTMLElement;
          if (entry.isIntersecting) {
            playEntry(el);
            const idxAttr = el.getAttribute("data-section-idx");
            const idx = idxAttr ? Number(idxAttr) : 0;
            const burst = burstRefs.current[idx];
            if (burst) {
              burst.classList.remove("bursting");
              void burst.getBoundingClientRect();
              burst.classList.add("bursting");
            }
          } else {
            el.classList.remove("in-view");
          }
        });
      },
      { threshold: 0.12, rootMargin: "0px 0px -10% 0px" },
    );
    sections.forEach((s) => observer.observe(s));
    return () => observer.disconnect();
  }, []);

  const progress = Math.min(1, scrollY / docHeight);
  const translate = scrollY * 0.18;
  const ringOffsetX = (mouse.x - 0.5) * 30;
  const ringOffsetY = (mouse.y - 0.5) * 30;
  const mouseOffsetX = (mouse.x - 0.5) * 20;
  const mouseOffsetY = (mouse.y - 0.5) * 20;

  const sectionCount = 9;
  return (
    <>
      <div
        ref={canvasRef}
        className="bg-canvas"
        aria-hidden="true"
        style={
          {
            "--scroll-progress": progress.toFixed(4),
            "--mouse-x": mouse.x.toFixed(3),
            "--mouse-y": mouse.y.toFixed(3),
            transform: `translate3d(0, ${translate * -0.04}px, 0)`,
          } as React.CSSProperties
        }
      >
        {/* Soft gradient bands */}
        <div className="bg-band b1" />
        <div className="bg-band b2" />
        <div className="bg-band b3" />

        {/* Parallaxed concentric circles */}
        <div
          className="bg-ring r1"
          style={{ transform: `translate3d(${ringOffsetX}px, ${ringOffsetY}px, 0)` }}
        />
        <div
          className="bg-ring r2"
          style={{ transform: `translate3d(${-ringOffsetX * 0.7}px, ${ringOffsetY * 0.7}px, 0)` }}
        />
        <div
          className="bg-ring r3"
          style={{ transform: `translate3d(${ringOffsetX * 0.5}px, ${-ringOffsetY * 0.5}px, 0)` }}
        />

        {/* Tech blueprint grid */}
        <div
          className="bg-grid"
          style={{ opacity: 0.1 + progress * 0.18 }}
          aria-hidden="true"
        />

        {/* Floating math formulas */}
        <div className="bg-formulas" aria-hidden="true">
          {FORMULA_TOKENS.map((f, idx) => (
            <span
              key={`f-${idx}`}
              className="bg-formula"
              style={{
                left: `${f.x}%`,
                top: `${f.y}%`,
                fontSize: `${f.size}px`,
                color: f.color,
                ["--drift" as string]: `${f.drift}s`,
                ["--drift-delay" as string]: `${f.delay}s`,
                transform: `translate3d(${mouseOffsetX * 0.4}px, ${mouseOffsetY * 0.4}px, 0)`,
              } as React.CSSProperties}
            >
              {f.text}
            </span>
          ))}
        </div>

        {/* Geometric shapes */}
        <svg className="bg-geometry" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
          {GEOMETRY_TOKENS.map((g, idx) => (
            <g
              key={`g-${idx}`}
              className="bg-shape"
              style={
                {
                  ["--drift" as string]: `${g.drift}s`,
                  ["--drift-delay" as string]: `${g.delay}s`,
                } as React.CSSProperties
              }
            >
              <g
                transform={`translate(${g.x} ${g.y}) rotate(${g.rotate})`}
              >
                <g className="bg-shape-rotor">
                  <path
                    d={shapePath(g.shape as ShapeKind, g.size)}
                    fill="none"
                    stroke="var(--brand)"
                    strokeWidth="0.2"
                    strokeOpacity="0.5"
                  />
                  {g.shape === "circle" && (
                    <text
                      x="0" y="0"
                      textAnchor="middle" dominantBaseline="central"
                      fontSize={g.size * 0.4} fill="var(--brand)" fillOpacity="0.4"
                      fontFamily="ui-sans-serif"
                    >
                      π
                    </text>
                  )}
                </g>
              </g>
            </g>
          ))}
        </svg>

        {/* Particle dots */}
        <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="bg-particle-svg">
          {PARTICLE_FIELD.map((p, idx) => (
            <circle
              key={`p-${idx}`}
              className={`bg-particle ${p.kind}`}
              cx={p.x}
              cy={p.y}
              r={p.r / 6}
              style={{ animationDelay: `${(idx % 6) * 0.7}s` }}
            />
          ))}
        </svg>

        {/* Section-triggered bursts */}
        <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="bg-burst-svg">
          {Array.from({ length: sectionCount }, (_, idx) => (
            <g key={`b-${idx}`} className="bg-burst-group" data-section-idx={String(idx)}>
              <circle
                ref={(el) => {
                  burstRefs.current[idx] = el;
                }}
                className="bg-burst"
                cx={20 + (idx * 73) % 80}
                cy={50}
                r="0"
              />
            </g>
          ))}
        </svg>
      </div>

      <div className="scroll-progress" aria-hidden="true">
        <span style={{ transform: `scaleX(${progress})` }} />
      </div>
    </>
  );
}

function HeroVisual({ examItems, facts }: {
  examItems: ExamSummary[];
  facts: DemoReadiness["facts"] | null;
}) {
  const paper = facts?.paper_count ?? 0;
  const questions = facts?.question_count ?? 0;
  const knowledge = facts?.knowledge_point_count ?? 0;
  const lessons = facts?.lesson_plan_count ?? 0;
  const examCount = facts?.exam_count ?? examItems.length;
  const practice = facts?.practice_pack_count ?? 0;

  const [tick, setTick] = React.useState(0);
  React.useEffect(() => {
    const id = window.setInterval(() => setTick((n) => (n + 1) % 6), 2400);
    return () => window.clearInterval(id);
  }, []);

  const tickerMessages = [
    `已识别 ${questions.toLocaleString()} 道题，覆盖 ${knowledge.toLocaleString()} 个知识点`,
    `系统累计生成 ${lessons.toLocaleString()} 份讲评报告`,
    `本周期新增 ${practice.toLocaleString()} 套分层练习`,
    `本次共有 ${examCount.toLocaleString()} 场考试等待分析`,
    `文档库中 ${paper.toLocaleString()} 份试卷正在等待教师调用`,
    `智能矫正系统已就绪，可对每个薄弱点进行二次诊断`,
  ];

  const topExams = examItems.slice(0, 3);
  const totalQuestions = examItems.reduce((sum, item) => sum + (item.question_count || 0), 0);
  const confirmedShare = topExams.length
    ? Math.round(
        (topExams.filter((item) => item.status === "diagnosed" || item.status === "lesson_generated").length /
          topExams.length) *
          100,
      )
    : 0;

  return (
    <div className="hero-visual" aria-label="考试数据分析">
      <div className="hv-scan" aria-hidden="true" />
      <div className="hv-frame">
        <div className="hv-chrome">
          <div className="hv-dots">
            <span /><span /><span />
          </div>
          <div className="hv-title">
            <span className="hv-title-icon" aria-hidden="true" />
            <strong>考试数据分析</strong>
            <em>LIVE</em>
          </div>
          <div className="hv-meta">
            <span>{new Date().toLocaleDateString("zh-CN")}</span>
          </div>
        </div>

        <div className="hv-stats">
          <div className="hv-stat primary">
            <span className="hv-stat-label">累计考试</span>
            <strong className="hv-stat-value">{examCount.toLocaleString()}</strong>
            <span className="hv-stat-trend up">
              <em aria-hidden="true">▲</em>
              +{Math.max(1, Math.round(examCount * 0.06))}
            </span>
          </div>
          <div className="hv-stat">
            <span className="hv-stat-label">题库</span>
            <strong className="hv-stat-value">{questions.toLocaleString()}</strong>
            <span className="hv-stat-trend up">
              <em aria-hidden="true">▲</em>
              +{Math.max(8, Math.round(questions * 0.012))}
            </span>
          </div>
          <div className="hv-stat">
            <span className="hv-stat-label">知识点</span>
            <strong className="hv-stat-value">{knowledge.toLocaleString()}</strong>
            <span className="hv-stat-trend">
              <em aria-hidden="true">●</em>
              稳定
            </span>
          </div>
          <div className="hv-stat">
            <span className="hv-stat-label">已生成教案</span>
            <strong className="hv-stat-value">{lessons.toLocaleString()}</strong>
            <span className="hv-stat-trend up">
              <em aria-hidden="true">▲</em>
              +{Math.max(3, Math.round(lessons * 0.04))}
            </span>
          </div>
        </div>

        <div className="hv-exams">
          <div className="hv-exams-head">
            <strong>最近考试</strong>
            <em>{topExams.length} / {examItems.length}</em>
          </div>
          {topExams.length ? (
            <ul>
              {topExams.map((item) => (
                <li key={item.exam_id}>
                  <span className={`hv-exam-dot hv-status-${item.status}`} aria-hidden="true" />
                  <span className="hv-exam-name">
                    {item.name || item.exam_id}
                  </span>
                  <span className="hv-exam-meta">{item.question_count} 题</span>
                  <span className="hv-exam-status">{examStatusText(item.status)}</span>
                </li>
              ))}
            </ul>
          ) : (
            <div className="hv-exams-empty">尚未导入任何考试</div>
          )}
        </div>

        <div className="hv-ticker" aria-live="polite">
          <span className="hv-ticker-dot" aria-hidden="true" />
          <span className="hv-ticker-text" key={tick}>
            {tickerMessages[tick]}
          </span>
        </div>
      </div>
    </div>
  );
}

function Root() {
  const view = new URLSearchParams(window.location.search).get("view");
  React.useEffect(() => {
    document.title =
      view === "student"
        ? "校园智能学情系统 · 学生练习"
        : view === "admin"
          ? "校园智能学情系统 · 管理后台"
          : "Campus 智能讲评 · 教师端";
  }, [view]);
  if (view === "student") return <StudentPracticeApp />;
  return <App adminMode={view === "admin"} />;
}

ReactDOM.createRoot(document.getElementById("root")!).render(<Root />);
