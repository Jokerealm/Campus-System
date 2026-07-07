# campus-system-p2

`campus-system-p2` 是 Campus AI 教育系统的 P2 教师端子系统。它负责把考试文件、P1 结构化结果和 P3 题库能力组织成教师可用的一次考试分析闭环：考试创建、文件上传、结构化结果查看、知识点诊断、讲评报告和 Word 教案导出。

## 重要说明：试卷到底输入什么？

已核验 `systemdesign.docx`：

- 完整系统的教师入口是上传阅卷 Excel，以及 Word、PDF、图片等试卷文件。
- 文档第 7.2 节规定 P2 的上传接口 `POST /exams/{exam_id}/files` 接收 `score_excel` 或 `paper`，文件可以是 Excel、Word、PDF 或图片。
- 文档第 7.3 节规定 P2 不自己解析 Word/PDF/图片，而是在内部调用 P1：
  - `POST /parse/score-excel`
  - `POST /parse/paper`
- P1 返回结构化题目后，P2 才进入教师校正、知识点确认和诊断分析。

因此，当前独立 P2 包的直接联调输入是 P1 解析后的 `paper.v0.1 JSON` 加成绩表。它不是要让最终老师手动准备 JSON，而是在 P1 尚未稳定接入时，用 JSON 作为 P1 输出的 mock 数据先跑通 P2。

## 快速开始

### 1. 获取代码

```powershell
git clone git@github.com:EmbedKun/Campus-System-P2.git
cd Campus-System-P2
```

### 2. 安装后端依赖

```powershell
python -m pip install -r backend\requirements.txt
```

### 3. 安装前端依赖

```powershell
cd frontend
pnpm install
cd ..
```

### 4. 启动后端

```powershell
cd backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
cd ..
```

### 5. 启动前端

另开一个终端：

```powershell
cd frontend
pnpm dev
```

默认打开：

```text
http://127.0.0.1:5173
```

如果后端端口不是 `8000`，启动前端前设置：

```powershell
$env:VITE_API_BASE_URL="http://127.0.0.1:<后端端口>"
pnpm dev
```

### 6. 一键验证

```powershell
python scripts\p2_smoke_test.py
```

期望输出包含：

```text
campus-system-p2 smoke test passed
questions=18
p3_requests=8
```

## P2 完成情况表

| 模块 | 状态 | 说明 |
|---|---|---|
| P1 结构化试卷 JSON 读取 | 已完成 | 支持 `paper.v0.1`，对应 P1 `/parse/paper` 结果的联调形态 |
| 成绩表读取 | 已完成 | 支持 `.xlsx`、`.xlsm`、`.csv`、`.txt` |
| 逐题匹配与得分率计算 | 已完成 | 支持普通题号和 `17(1)` 这类小题 |
| 知识点确认结果生成 | 已完成 | 第一阶段使用 P1 候选知识点，保留后续教师确认接口 |
| 薄弱知识点诊断 | 已完成 | 按知识点聚合得分率、失分率、相关题号和建议 |
| 教师讲评报告 | 已完成 | 支持 JSON、Markdown、Word 导出 |
| 页面端工作台 | 已完成 | 支持点击式上传、Demo、筛选、导出 |
| P2 标准接口 | 已完成 | 已补齐 `systemdesign.docx` 第 7 节核心接口 |
| P3 推荐题联动 | 部分完成 | P2 已生成检索请求；真实题库检索结果等待 P3 对接 |
| Word/PDF/图片直接解析 | 不属于 P2 | 文档规定由 P1 `/parse/paper` 完成，当前 P2 独立包会提示需要 P1 |
| 本地大模型部署 | 后续阶段 | 第一阶段用规则和候选知识点先跑通闭环 |

## TODO List

- 对接真实 P1：让 `/exams/{exam_id}/parse` 调用 P1 的 `/parse/score-excel` 和 `/parse/paper`。
- 对接真实 P3：把诊断后的薄弱知识点传给 `/questions/search` 和 `/practice-packs`。
- 增加教师人工确认页面：支持逐题修正题干、题型、满分和知识点。
- 增加真实考试列表和本地持久化：当前标准接口使用内存态，适合 Demo 和联调。
- 完善 Word 教案模板：接入学校模板、Logo、页眉页脚和练习题推荐。
- 增加个人学生报告：需要成绩表从班级均分扩展到学生逐题矩阵。
- 打包桌面版：保持 GUI 与算法逻辑分离，后续可用 PyInstaller 或桌面壳封装。

## 页面端使用教程

### 查看 Demo

1. 启动后端和前端。
2. 打开前端页面。
3. 页面会自动载入 Demo 分析结果。
4. 点击“重点 / 薄弱 / 观察 / 稳定”筛选题目。
5. 点击“导出 Word”或“导出 Markdown”下载讲评报告。

### 使用自己的数据

1. 点击“下载示例 JSON”和“下载示例成绩”查看输入格式。
2. 上传 P1 输出的 `paper.v0.1 JSON`。
3. 上传阅卷成绩表。
4. 可填写考试编号和班级名称。
5. 点击“开始分析”。
6. 页面会展示考试概况、优先讲评题、逐题分析、知识点诊断和报告导出入口。

注意：如果手上只有 Word/PDF/图片试卷，需要先经过 P1 解析；P2 独立包不直接做 OCR、切题或版面解析。

## 命令行使用教程

校验 P1 结构化试卷：

```powershell
python scripts\validate_normalized_paper.py examples\normalized_paper_demo.json
```

运行一次 P2 分析：

```powershell
python scripts\p2_analyze_exam.py `
  --paper examples\normalized_paper_demo.json `
  --scores examples\sample_exam_scores.xlsx `
  --exam-id exam_demo_001 `
  --class-name 示例班级 `
  --out data\exams\exam_demo_001_analysis.json
```

输出文件：

```text
data/exams/exam_demo_001_analysis.json
data/exams/exam_demo_001_report.md
data/exams/exam_demo_001_report.docx
```

运行完整烟测：

```powershell
python scripts\p2_smoke_test.py
```

烟测覆盖：

- P1 JSON 结构校验。
- P2 service 直接分析。
- JSON / Markdown / DOCX 导出。
- 页面便捷 API。
- `systemdesign.docx` 第 7 节对应的 P2 标准接口主流程。

## 接口设计

### 接口核验结论

已核验 `systemdesign.docx`，当前项目包含两组接口：

1. 标准 P2 接口：对齐文档第 7 节，面向最终系统集成。
2. Demo 便捷接口：`/api/p2/*`，面向当前前端和独立演示。

标准接口已与 Word 文档中的核心 P2 流程保持一致；便捷接口是为了在 P1/P3 未完全接入前简化本地演示。

### 标准 P2 接口

| 方法 | 路径 | 文档对应 | 当前状态 |
|---|---|---|---|
| `POST` | `/exams` | 7.1 创建考试 | 已实现 |
| `POST` | `/exams/{exam_id}/files` | 7.2 上传考试文件 | 已实现 |
| `POST` | `/exams/{exam_id}/parse` | 7.3 启动考试解析 | 已实现；JSON mock 可直接跑通，Word/PDF 需 P1 |
| `GET` | `/exams/{exam_id}/structure` | 7.4 获取考试结构化结果 | 已实现 |
| `PUT` | `/exams/{exam_id}/questions/{exam_question_id}` | 7.5 教师修正题目结构 | 已实现基础更新 |
| `PUT` | `/exams/{exam_id}/questions/{exam_question_id}/knowledge-tags` | 7.6 教师确认知识点 | 已实现基础更新 |
| `POST` | `/exams/{exam_id}/diagnostics/run` | 7.7 运行考试诊断 | 已实现 |
| `GET` | `/exams/{exam_id}/diagnostics/{diagnostic_id}` | 7.8 获取诊断报告 | 已实现 |
| `POST` | `/exams/{exam_id}/lesson-plans` | 7.9 生成 Word 教案 | 已实现元数据返回；真实模板增强待做 |

### Demo 便捷接口

| 方法 | 路径 | 用途 |
|---|---|---|
| `GET` | `/api/health` | 服务健康检查 |
| `GET` | `/api/model/status` | 模型状态说明 |
| `GET` | `/api/p2/demo` | 获取内置 Demo 分析 |
| `GET` | `/api/p2/examples/paper` | 下载示例 `paper.v0.1 JSON` |
| `GET` | `/api/p2/examples/scores` | 下载示例成绩表 |
| `POST` | `/api/p2/analyze` | 上传 JSON 和成绩表，直接运行 P2 分析 |
| `POST` | `/api/p2/reports/docx` | 导出 Word 报告 |
| `POST` | `/api/p2/reports/markdown` | 导出 Markdown 报告 |

## 项目结构

```text
campus-system-p2/
  backend/                  # FastAPI 后端
  campus_p2_core/           # P2 核心算法与契约
  docs/                     # P2 任务和接口说明
  examples/                 # Demo 输入数据
  frontend/                 # React/Vite 前端
  scripts/                  # 校验和烟测脚本
```

## 交付判断

当前 P2 已满足第一阶段 Demo 和联调要求：

- 独立页面可操作。
- 核心分析闭环可跑通。
- 标准接口主流程已按 Word 文档补齐。
- 便捷接口支持快速演示。
- 对 P1/P3 的真实依赖已明确留口。
