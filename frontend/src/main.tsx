import React from "react";
import ReactDOM from "react-dom/client";
import "./styles.css";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

type Severity = "critical" | "weak" | "watch" | "stable";
type QuestionFilter = Severity | "all";

type KnowledgePointRef = {
  code: string;
  name: string;
  confidence?: number;
  source?: string;
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
  question_type: string | null;
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

type P2ExamAnalysis = {
  exam_id: string;
  paper_id: string;
  class_name: string;
  question_analysis: QuestionAnalysis[];
  knowledge_diagnostics: KnowledgeDiagnostic[];
  teaching_report: TeachingReport;
  warnings: string[];
};

const severityText: Record<Severity, string> = {
  critical: "重点讲评",
  weak: "薄弱",
  watch: "观察",
  stable: "稳定",
};

const filters: Array<{ key: QuestionFilter; label: string }> = [
  { key: "all", label: "全部" },
  { key: "critical", label: "重点" },
  { key: "weak", label: "薄弱" },
  { key: "watch", label: "观察" },
  { key: "stable", label: "稳定" },
];

function pct(value: number) {
  return `${Math.round(value * 1000) / 10}%`;
}

function formatScore(value: number) {
  return Number.isInteger(value) ? `${value}` : value.toFixed(1);
}

function knowledgeNames(points: KnowledgePointRef[]) {
  return points.map((item) => item.name).join("、") || "待确认";
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

async function apiGet<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`);
  if (!response.ok) throw new Error(path);
  return response.json();
}

function App() {
  const [analysis, setAnalysis] = React.useState<P2ExamAnalysis | null>(null);
  const [paperFile, setPaperFile] = React.useState<File | null>(null);
  const [scoreFile, setScoreFile] = React.useState<File | null>(null);
  const [examId, setExamId] = React.useState(makeExamId);
  const [className, setClassName] = React.useState("");
  const [questionFilter, setQuestionFilter] = React.useState<QuestionFilter>("all");
  const [busy, setBusy] = React.useState(true);
  const [downloading, setDownloading] = React.useState(false);
  const [error, setError] = React.useState("");

  React.useEffect(() => {
    void loadDemo();
  }, []);

  async function loadDemo() {
    setBusy(true);
    setError("");
    try {
      setAnalysis(await apiGet<P2ExamAnalysis>("/api/p2/demo"));
      setQuestionFilter("all");
    } catch {
      setError("后端服务未连接，请先启动本地服务后刷新页面。");
    } finally {
      setBusy(false);
    }
  }

  async function runAnalysis() {
    if (!paperFile || !scoreFile) {
      setError("请先选择 P1 结构化试卷 JSON 和成绩表。");
      return;
    }

    setBusy(true);
    setError("");
    const data = new FormData();
    data.append("paper_file", paperFile);
    data.append("score_file", scoreFile);
    data.append("exam_id", examId.trim() || makeExamId());
    data.append("class_name", className.trim() || "未命名班级");

    try {
      const response = await fetch(`${API_BASE}/api/p2/analyze`, { method: "POST", body: data });
      if (!response.ok) {
        const detail = await response.json();
        throw new Error(detail?.detail?.message || "分析失败");
      }
      setAnalysis(await response.json());
      setQuestionFilter("all");
    } catch (err) {
      setError(err instanceof Error ? err.message : "分析失败");
    } finally {
      setBusy(false);
    }
  }

  async function downloadReport(kind: "docx" | "markdown") {
    if (!analysis) return;
    setDownloading(true);
    setError("");
    try {
      const response = await fetch(`${API_BASE}/api/p2/reports/${kind === "docx" ? "docx" : "markdown"}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
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

  const overall = overallRate(analysis);
  const weakKnowledge = analysis?.knowledge_diagnostics.filter((item) => item.severity !== "stable") ?? [];
  const priorityQuestions = analysis?.question_analysis.slice(0, 6) ?? [];
  const filteredQuestions =
    analysis?.question_analysis.filter((item) => questionFilter === "all" || item.severity === questionFilter) ?? [];

  return (
    <main id="main-body">
      <header className="site-header">
        <div>
          <p className="eyebrow">campus-system-p2</p>
          <h1>教师端智能考试分析</h1>
        </div>
        <nav aria-label="页面导航">
          <a href="#workspace">开始</a>
          <a href="#overview">概况</a>
          <a href="#questions">题目</a>
          <a href="#knowledge">知识点</a>
          <a href="#report">报告</a>
        </nav>
      </header>

      <figure className="hero-media">
        <img src="/images/classroom-discussion.jpg" alt="课堂讨论场景" />
      </figure>

      {error && <p className="notice danger">{error}</p>}

      <section id="workspace" className="workspace">
        <div className="section-heading">
          <p className="eyebrow">Start</p>
          <h2>分析工作台</h2>
        </div>

        <div className="upload-grid">
          <FileInput
            accept=".json"
            file={paperFile}
            label="P1 结构化试卷"
            note="paper.v0.1 JSON"
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
        </div>

        <div className="actions">
          <button className="primary" onClick={() => void runAnalysis()} disabled={busy}>
            {busy ? "正在分析" : "开始分析"}
          </button>
          <button onClick={() => void loadDemo()} disabled={busy}>
            查看示例
          </button>
          <a className="button-link" href={`${API_BASE}/api/p2/examples/paper`}>
            下载示例 JSON
          </a>
          <a className="button-link" href={`${API_BASE}/api/p2/examples/scores`}>
            下载示例成绩
          </a>
        </div>
      </section>

      <section id="overview">
        <div className="section-heading">
          <p className="eyebrow">Overview</p>
          <h2>考试概况</h2>
        </div>
        <div className="metric-grid">
          <Metric label="整体得分率" value={analysis ? pct(overall) : "--"} />
          <Metric label="匹配题目" value={analysis ? `${analysis.question_analysis.length}` : "--"} />
          <Metric label="重点讲评" value={`${countBySeverity(analysis, "critical")}`} />
          <Metric label="薄弱知识点" value={analysis ? `${weakKnowledge.length}` : "--"} />
        </div>
        {analysis?.teaching_report.summary && <p className="summary">{analysis.teaching_report.summary}</p>}
      </section>

      <section className="priority-section">
        <div className="section-heading">
          <p className="eyebrow">Focus</p>
          <h2>优先讲评</h2>
        </div>
        <div className="priority-list">
          {priorityQuestions.map((item) => (
            <article key={item.question_no} className="priority-item">
              <div>
                <span className={`severity ${item.severity}`}>{severityText[item.severity]}</span>
                <h3>第 {item.question_no} 题</h3>
              </div>
              <p>
                得分率 {pct(item.score_rate)}，均分 {formatScore(item.avg_score)} / {formatScore(item.full_score)}
              </p>
              <p>{knowledgeNames(item.confirmed_knowledge_points)}</p>
            </article>
          ))}
        </div>
      </section>

      <section id="questions">
        <div className="section-heading">
          <p className="eyebrow">Questions</p>
          <h2>逐题分析</h2>
        </div>
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
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>题号</th>
                <th>得分率</th>
                <th>均分/满分</th>
                <th>状态</th>
                <th>知识点</th>
                <th>题干</th>
              </tr>
            </thead>
            <tbody>
              {filteredQuestions.map((item) => (
                <tr key={item.question_no}>
                  <td>{item.question_no}</td>
                  <td>{pct(item.score_rate)}</td>
                  <td>
                    {formatScore(item.avg_score)} / {formatScore(item.full_score)}
                  </td>
                  <td>
                    <span className={`severity ${item.severity}`}>{severityText[item.severity]}</span>
                  </td>
                  <td>{knowledgeNames(item.confirmed_knowledge_points)}</td>
                  <td>{item.stem_text || "待补充"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section id="knowledge">
        <div className="section-heading">
          <p className="eyebrow">Knowledge</p>
          <h2>知识点诊断</h2>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>知识点</th>
                <th>得分率</th>
                <th>状态</th>
                <th>相关题号</th>
                <th>讲评建议</th>
              </tr>
            </thead>
            <tbody>
              {analysis?.knowledge_diagnostics.map((item) => (
                <tr key={item.code}>
                  <td>{item.name}</td>
                  <td>{pct(item.score_rate)}</td>
                  <td>
                    <span className={`severity ${item.severity}`}>{severityText[item.severity]}</span>
                  </td>
                  <td>{item.related_question_nos.join(", ")}</td>
                  <td>{item.suggestion}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section id="report">
        <div className="section-heading">
          <p className="eyebrow">Report</p>
          <h2>讲评报告</h2>
        </div>
        <div className="actions">
          <button className="primary" onClick={() => void downloadReport("docx")} disabled={!analysis || downloading}>
            导出 Word
          </button>
          <button onClick={() => void downloadReport("markdown")} disabled={!analysis || downloading}>
            导出 Markdown
          </button>
        </div>
        <pre>{analysis?.teaching_report.markdown || ""}</pre>
      </section>

      {analysis?.warnings.length ? (
        <section>
          <div className="section-heading">
            <p className="eyebrow">Check</p>
            <h2>数据校验</h2>
          </div>
          <ul className="warning-list">
            {analysis.warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        </section>
      ) : null}

      <footer>campus-system-p2</footer>
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

ReactDOM.createRoot(document.getElementById("root")!).render(<App />);
