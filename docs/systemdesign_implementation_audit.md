# Campus-System 对照 systemdesign.docx 实现度审计

审计日期：2026-07-30  
基准文档：`systemdesign.docx`，版本 v0.1，日期 2026-06-30

## 结论

当前仓库已经具备第一阶段试运行的主要骨架：P1 Word 切题样例、P2 教师端分析工作台、P3 题库与学生训练服务都存在，并且 P2 与 P3 已经可以通过推荐题检索和训练包创建完成本地标准流程。前端上传流程已从便捷 `/api/p2/analyze` 切到标准 `/exams` 编排，能够创建考试、上传文件、解析、诊断、保存教师确认、生成 P3 训练包、生成 Word 教案，并从最近考试恢复历史分析、教案和训练包入口。统一前端已重新分层：默认教师页面向最终客户，只展示 Word 试卷上传、成绩表上传、学情诊断、教师确认、练习建议和讲评报告；AI 题审核、系统审计、服务状态和学生练习预览移入 `?view=admin` 管理后台；学生练习保留为独立 `?view=student` 页面。

但它还不能宣称“完整上线”：生产级 P1 异步编排、PDF/图片 OCR/VLM、完整知识点字典、50 套题库正式授权审核、统一账号鉴权、生产级审计策略和学校 Word 模板仍需补齐。P2 当前已有本地 SQLite 持久化，适合第一阶段本机试运行。

## 第一版最小流程状态

| systemdesign 第一版要求 | 当前证据 | 状态 |
| --- | --- | --- |
| Excel 阅卷统计解析 | `campus_p2/p2_teacher/score_loader.py` 支持 XLSX/CSV；`scripts/p2_smoke_test.py` 已通过 | 可演示 |
| Word 试卷题目拆分 | `campus_p1/word_cutter_system` 已有 Word 切题脚本和样例输出；`/api/ai/v1/parse/paper` 已统一暴露 Word `.docx` 本地演示接口 | 可演示 |
| 教师校正和知识点确认 | `frontend/src/main.tsx` 提供逐题题号、题干、题型、满分、知识点编辑；P2 标准接口支持 PUT 更新并写入 SQLite | 可演示 |
| 班级考试诊断 | `campus_p2/p2_teacher/analyzer.py` 输出逐题、知识点诊断和 `knowledge_tag_coverage` 覆盖率；前端概况卡和标准诊断 summary 均展示该指标 | 可演示 |
| Word 讲评教案生成 | `campus_p2/p2_teacher/report_exporter.py` 可导出 DOCX；标准 `/lesson-plans` 返回下载 URL；报告已展示课堂目标、讲评安排、知识点覆盖率、优先讲评题和推荐练习，并隐藏题库内部编号 | 可演示，学校模板待接入 |
| 按薄弱知识点检索题库推荐题 | 新增 `campus_p2/p2_teacher/p3_adapter.py`，支持 P3 HTTP 和 fixture fallback；前端新增“推荐练习”和“生成训练包” | 可演示 |
| 管理后台服务状态 | 新增 `/api/demo/readiness`，聚合输入处理、教师端本地考试库、题库规模、模型配置状态、安全审计状态、上传限制和文件访问边界；客户可见考试/教案/训练包与系统测试数据分开统计；默认教师页隐藏工程化状态，管理后台单独展示 | 可试运行 |

## P1 AI 能力服务

| 文档要求 | 当前状态 | 缺口 |
| --- | --- | --- |
| Excel 解析接口 `/parse/score-excel` | 已新增本地演示接口 `/api/ai/v1/parse/score-excel`，返回结构化得分记录 | 生产形态仍需异步任务、文件存储和审计日志 |
| Word/PDF/图片试卷解析 `/parse/paper` | Word `.docx` 已新增本地演示接口 `/api/ai/v1/parse/paper`，并已接入 P2 标准 `/exams/{exam_id}/parse` 流程；PDF OCR 仍处于实验路线 | PDF/图片质量仍需长期优化，生产形态仍需异步任务队列 |
| 知识点候选 `/knowledge/tag` | 已新增本地演示接口 `/api/ai/v1/knowledge/tag`；优先读取 P3 知识点字典，可选调用 OpenAI-compatible LLM，未配置 key 时用规则兜底 | 仍需结合正式知识图谱做人工清洗和标注质量评估 |
| 错题识别、引导讲解、变式题 | 已新增 `/api/ai/v1/wrong-question/recognize`、`/api/ai/v1/jobs/{job_id}`、`/api/ai/v1/wrong-question/recognize/{job_id}/result`、`/api/ai/v1/explanations/guided/next`、`/api/ai/v1/questions/variants/generate` 本地演示接口；引导和变式可选调用 OpenAI-compatible LLM，失败时规则兜底 | 真实图片 OCR/VLM、题目质量评估和生产任务队列仍需接入 |

## P2 教师端

| 文档要求 | 当前状态 | 缺口 |
| --- | --- | --- |
| 考试创建、上传、解析、结构化结果 | FastAPI 标准接口已覆盖 `/exams` 主流程，并新增 `GET /exams` 考试列表；前端“开始分析”已走标准流程，最近考试可一键恢复分析；客户视图默认隐藏 smoke/system 测试数据，接口可用 `include_system=true` 查看完整列表 | 本地 SQLite 可持久化；正式多用户权限与 PostgreSQL 部署待补 |
| 教师人工确认 | 前端和接口均具备；标准 PUT 会同步分析对象并写入 SQLite | 便捷 API 仍保留用于示例和回退 |
| 诊断报告 | 已完成基础诊断、知识点覆盖率、优先讲评题；`systemdesign.docx` 要求的“诊断报告中必须标明知识点覆盖率”已进入分析对象、前端概况、Markdown/Word 报告和 smoke 断言 | 错因层面目前主要是规则建议，不是完整错因模型 |
| P3 推荐题和训练包 | 已从“仅生成请求”升级为返回推荐题结果，并新增 `/exams/{exam_id}/practice-packs` 创建训练包；新增 P2 `/student/practice/recommendations`、`/student/practice/answers`、`/student/practice/progress`、`/student/practice/history`、`/student/reports/personal` 与 `/student/wrong-questions/*` 聚合代理，供前端学生练习页调用 P3 学生错题上传、识别确认、引导讲解、推荐、作答、历史筛选、掌握度进度和个人学习报告接口 | 真实 P3 服务未启动时使用 fixture fallback 或本地训练包结果；正式学生端仍需登录和生产级 OCR/VLM |
| Word 教案 | 兼容接口和标准 `/lesson-plans` 均可生成 DOCX，标准接口返回下载 URL；`GET /lesson-plans` 可恢复历史教案入口 | 学校正式模板、页眉页脚、Logo、格式规范待接入 |
| AI 生成题审核 | 已新增 P2 `/ai-generated-questions`、`/ai-generated-questions/{id}/review` 聚合接口；前端“AI 题目审核”可将 P1 变式题送入 P3 待审队列并执行通过/驳回 | P3 离线时使用 P2 本地队列；正式审核角色、批量审核和质量标注待增强 |
| 安全与审核审计 | P2 SQLite 已记录考试创建、文件上传、解析、教师修正、知识点确认、诊断、训练包、AI 题审核、教案生成和下载；新增 `/audit-logs` 与管理后台“系统审计”视图；标准教师端接口已支持可配置的本地试运行身份/租户请求头、Bearer token 和本地 JSON 账号目录允许名单；新增 `/auth/session` 返回当前会话、角色、账号来源、账号目录摘要和权限摘要，不返回真实 token；受控模式下学生角色访问教师考试、教案、AI 题审核和审计工作区会返回 403，账号目录必需时未入目录的教师/学生/服务账号会返回 403；管理后台提供身份入口，顶部产品导航展示当前会话权限；上传入口已校验扩展名和大小，并记录 `size_bytes`、`sha256`；`/api/assets` 已收窄为仅暴露 P1 解析产物目录，教案和样例文件走显式下载接口 | 生产级不可篡改日志、正式 RBAC、SSO/OIDC/LDAP、租户隔离和长期归档策略待补 |

## P3 题库与学生训练

| 文档要求 | 当前状态 | 缺口 |
| --- | --- | --- |
| 知识点字典维护和查询 | Django 模型、fixture、查询 API 已实现；新增 `import_p1_papers_to_bank` 可从 50 套 P1 输出创建初中细粒度知识点 | 运行时创建的知识点仍需人工清洗、去重、对齐正式课程标准 |
| 题库导入和检索 | `questions/import`、`questions/search` 已实现并测试；50 套 P1 真题输出已可一键导入 P3 | 题目来源授权、审核状态流和图片资源展示仍需产品化 |
| 题库规模和状态统计 | 新增 `GET /api/resource/v1/stats`，返回知识点、题库题、训练包、AI 生成题和审核状态统计；P2 readiness 优先读取该接口 | 正式运营看板仍需按学校、学段、来源、审核状态展开 |
| 训练包创建 | `practice-packs` 已实现并测试 | 发布、分发、学生完成进度待补 |
| AI 生成题审核 | 候选保存、审核、通过后入库已实现并测试；P1 本地变式题接口可输出待审核题 | 生成质量、去重和正式审核策略待评估 |
| 学生错题训练 | 上传、识别轮询、确认、引导讲解、推荐、答题、练习历史、掌握度更新和个人学习报告均有接口；P1 本地错题识别、引导和变式接口已补齐；统一前端已加入 `?view=student` 学生练习页和教师端学生练习预览，可上传错题图片、查看识别结果、确认知识点、获取引导讲解、拉取 P3 推荐题、提交作答，并显示个人学习报告、正确率、最近作答、练习历史筛选和知识点掌握度看板 | 正式学生端仍需登录态和生产级 OCR/VLM |

## 知识点和题库入库核验

已用 SQLite 本地试运行库验证 P3 seed + P1 50 套真题输出加载：

- P1 输出规模：50 套中考数学真题卷，1248 道题，951 张题图，其中 1247 道题带 `qwen_analysis.knowledge_points`
- P3 入库后基础规模：326 个知识点、1272 道 P1/seed 题库题；HTTP smoke 审核发布 AI 生成题后数量会继续小幅增长
- 题库构成：24 道基础 seed 题 + 1248 道 P1 真题输出
- 初中知识点：302 条，其中包含运行时创建的 283 个高频 AI 细粒度知识点
- 高中 seed 知识点：24 条
- `scripts/audit_knowledge_bank.py` 最新核验：`imported_questions_found=1248`，`questions_with_p3_knowledge=1248`，`missing_imported_questions=0`，`questions_without_p3_knowledge=0`，`missing_specific_knowledge_points=0`
- 覆盖率：`question_import_coverage=1.0`，`question_knowledge_coverage=1.0`，`specific_knowledge_coverage=1.0`
- 高中 seed 知识点路径和 19 道高中推荐题已清理为可读题干、答案和解析，不再使用 `???` 占位符；`p3_sqlite_smoke.py` 会断言高中知识点和高中推荐题中不再出现占位符
- `POST /api/resource/v1/questions/search` 针对 `kp_math_junior_statistics` 返回 5 道 P1 真题，`need_ai_generation=False`
- `POST /api/resource/v1/questions/search` 针对 `kp_math_8_function_linear`、`kp_math_9_circle`、`kp_math_junior_algebra_ops` 均可返回真题结果
- P2 `/api/p2/demo` 已通过 `p3-http` 返回推荐题结果

结论：50 套题目已经可以通过管理命令和启动脚本导入 P3 本地库；知识点不再是“未入库”，但当前仍是试运行级映射，需要后续人工清洗为正式知识图谱。

## 验证记录

统一 preflight：

```powershell
.\.venv\Scripts\python.exe scripts\preflight_release_check.py
```

结果：preflight 会串联 Python 编译、密钥扫描、PowerShell 启停与 LLM 配置脚本语法检查、LLM 配置脚本空 key 生成 smoke、`.env` 编码兼容 smoke、P2 smoke、P3 smoke、知识点入库覆盖审计、`systemdesign.docx` 第一阶段验收审计、LLM 配置 smoke、可选 live LLM smoke 和前端构建；客户演示服务已启动时可加 `--full-stack` 纳入真实 HTTP 闭环，部署前可加 `--require-live-llm` 强制验证真实模型连通性。

GitHub Actions 门禁：已新增 `.github/workflows/release-preflight.yml`，在 push、pull request 和手动触发时使用 Windows runner 安装后端、P3、前端依赖，并执行 `scripts/preflight_release_check.py`。该 CI 默认不要求真实大模型密钥，仍会覆盖密钥扫描、PowerShell 启停与 LLM 配置脚本语法检查、LLM 配置脚本空 key 生成 smoke、`.env` 编码兼容 smoke、P2/P3 smoke、50 套题知识点入库审计、systemdesign 第一阶段验收审计、LLM 配置安全检查和前端构建。

```powershell
.\.venv\Scripts\python.exe scripts\systemdesign_acceptance_audit.py
```

结果：systemdesign 验收审计通过 69 项检查，包含 Word 手册关键条目抽取、P1/P2/P3 标准接口存在性、P2 分析契约字段、Word-only 试卷入口、50 套 P1 输出入库、1248/1248 道题知识点覆盖和 README 页面截图存在性。

```powershell
.\.venv\Scripts\python.exe scripts\p2_smoke_test.py
```

结果：P2 smoke test 通过，包含 18 道题、8 个 P3 检索请求，并确认 API 响应中有推荐题；同时覆盖 P1 本地成绩解析、Word 试卷解析、`/parse/paper/{job_id}/result`、`/parse/score-excel/{job_id}/result`、上传扩展名校验、`sha256` 文件元数据、P1 解析产物 `paper_url` 访问、`/api/assets` 不暴露仓库文件、知识点候选、错题识别、任务轮询、引导讲解、变式题生成，以及标准 `/exams` 流程、完整分析读取、知识点覆盖率、教师修正保存、知识点确认、考试列表、SQLite 落库、训练包创建与列表恢复、Word 教案列表和下载。

真实 HTTP 标准流程验证：

```text
parse_status=teacher_review
questions=18
recommendations=8
practice_pack_source=p3-http
practice_pack_questions=8
lesson_bytes=38328
latest_status=lesson_generated
```

本地 P2 SQLite 当前演示库计数验证：

```text
data/p2_demo.sqlite3
exams=9
exam_files=18
diagnostics=5
audit_logs=106
```

浏览器验证：默认教师端 `http://127.0.0.1:5176/?apiBase=http%3A%2F%2F127.0.0.1%3A8000` 的浏览器标题为“校园智能学情系统 · 教师工作台”，首屏标题为“考试讲评，从试卷开始”，顶部产品导航只显示“开始分析”；页面正文不包含旧阶段工程化词汇、`demo`、`样例`、`示例`、`P1`、`P2`、`P3`、`PDF`、`OCR`、`系统审计`、`日志`、`管理后台` 或 `学生练习`；`#student`、`#audit`、`#logs` 均未在默认教师页渲染；上传入口只接受 Word `.docx` 试卷，右侧信息改为客户可读的交付步骤。默认首屏为空状态，不自动加载内部数据，也不提供内部预览按钮。管理员端 `?view=admin` 单独保留服务状态、学生预览、AI 题审核和系统审计，且审核/审计区域不依赖某一场考试是否已载入；学生端 `?view=student` 保留独立练习页。默认教师页在桌面和约 390px 移动宽度下均无横向溢出。

```powershell
$env:P3_DATABASE_ENGINE='sqlite'
$env:P3_SQLITE_PATH='data\p3_test.sqlite3'
.\.venv\Scripts\python.exe campus_p3\backend\manage.py test resources students -v 1
```

结果：60 个 P3 测试通过，其中 1 个 SQLite 并发写压力用例按预期跳过。默认生产数据库 PostgreSQL 不跳过该类并发语义。

```powershell
$env:P3_DATABASE_ENGINE='sqlite'
$env:P3_SQLITE_PATH='data\p3_demo.sqlite3'
.\.venv\Scripts\python.exe campus_p3\backend\manage.py migrate --noinput
.\.venv\Scripts\python.exe campus_p3\backend\manage.py load_knowledge_points
.\.venv\Scripts\python.exe campus_p3\backend\manage.py load_question_bank
```

结果：加载 10 个知识点、5 道题库题。

最新 seed 扩展后加载结果为 34 个知识点、24 道题库题。

```powershell
.\.venv\Scripts\python.exe campus_p3\backend\manage.py import_p1_papers_to_bank
```

结果：导入 50 套 P1 输出，1248 道真题，创建 283 个高频细粒度 demo 知识点。

```powershell
.\.venv\Scripts\python.exe scripts\p3_sqlite_smoke.py
```

结果：P3 smoke 通过，`db_knowledge_points=326`，`db_questions>=1272`，`p1_imported_search_items=5`。基础 P1/seed 题库为 1272 道；题库数量会随着 HTTP smoke 中 AI 生成题审核发布而小幅增长。

```powershell
.\.venv\Scripts\python.exe scripts\llm_config_smoke.py
```

结果：LLM 配置 smoke 通过，使用临时测试 key 验证 `/api/model/status` 和 `/api/demo/readiness` 能正确显示大模型组件 ready，并断言响应中不会返回 key 本身；该验证不请求外部模型服务。

```powershell
.\.venv\Scripts\python.exe scripts\llm_live_smoke.py
```

结果：本地未配置 `.env` 真实 key 时，live smoke 安全跳过并输出 `api_key_leaked=false`；若部署前运行 `.\.venv\Scripts\python.exe scripts\llm_live_smoke.py --require`，则会通过 OpenAI-compatible `/models` 和 `/chat/completions` 做真实连通性门禁，且不会打印真实 API key。

```powershell
.\.venv\Scripts\python.exe scripts\full_stack_http_smoke.py --p2-url http://127.0.0.1:8000 --p3-url http://127.0.0.1:8103 --frontend-url http://127.0.0.1:5176
```

结果：真实 HTTP 全栈 smoke 通过，`readiness=ready`，`papers=50`，`questions>=1272`，`knowledge_points=326`，`teacher_session_role=teacher`，`student_session_role=student`，`identity_directory_source=builtin_demo`，`identity_directory_users=3`，`p3_search_items=5`，`student_practice_items=3`，`student_history_items=3`，`student_report_level=progressing`，`student_wrong_question=confirmed`，`student_variants=2`，`generated_review=approved`，`teacher_questions=18`，`teacher_knowledge_tag_coverage=1.0`，`teacher_practice_pack_questions=8`，`teacher_lesson_bytes=39037`。全栈 smoke 的一次性 AI 生成题发布使用固定 ID，后续重复验证不会继续增加题库题量；学生作答数和审计日志数会随 smoke 中学生作答和考试创建小幅增长。该脚本直接访问正在运行的 P2/P3/前端服务，覆盖 P2 `/health` 与 `/api/health`、P3 health、P3 stats、P3 题库检索、P2 readiness 五组件、教师/学生会话权限状态、账号目录摘要、学生错题上传、识别结果读取、知识点确认、引导讲解、学生练习推荐、学生作答掌握度、练习历史查询、个人学习报告、变式题生成、AI 生成题送审与教师审核、系统审计日志、`/api/assets` 仓库文件拒绝访问、前端 HTML 可访问性，以及真实 HTTP 下的教师端标准闭环：创建考试、上传试卷和成绩、解析、教师修正保存、知识点确认、知识点覆盖率、诊断、P3 训练包、Word 教案生成与下载、考试摘要恢复。

前端视觉 QA：`pnpm --dir frontend build` 通过；浏览器检查教师端 `http://127.0.0.1:5176/?apiBase=http%3A%2F%2F127.0.0.1%3A8000`、管理员端 `http://127.0.0.1:5176/?apiBase=http%3A%2F%2F127.0.0.1%3A8000&view=admin` 和学生端 `http://127.0.0.1:5176/?apiBase=http%3A%2F%2F127.0.0.1%3A8000&view=student`。默认教师端首屏只保留考试分析主流程；上传入口只接受 Word `.docx` 试卷；桌面宽度无横向溢出。管理员端保留服务状态、学生预览、AI 题审核和系统审计；学生端在约 375px 移动宽度下无横向溢出，标题字号与身份区已收敛为工作台密度。

一键启动脚本 `scripts/start_local_demo.ps1` 已增强为本地服务编排入口：读取本机 `.env`（不打印真实密钥）、迁移 P3 SQLite、导入 50 套 P1 真题输出、启动 P2/P3/前端，并等待 P3 health、P2 health、`/api/demo/readiness` 和前端页面全部可访问后输出 readiness、题库规模和日志目录。新增 `scripts/stop_local_demo.ps1` 只停止命令行中包含当前仓库路径且匹配 P2/P3/前端本地服务的进程；启动脚本会复用已健康服务，对占用端口但自检失败的当前仓库旧进程会自动停止并重启，对外部进程仍给出明确提示。启动脚本会优先使用 Codex bundled pnpm，找不到时自动使用 Windows PATH 中的 `pnpm`，并将组件状态摘要输出为 ASCII key，降低普通 Windows 终端编码和环境路径问题。前端输出地址会显式携带 `?apiBase=`，因此即使复用已有 Vite 进程，也会绑定到本次启动的 P2 端口。

## 近期优先 TODO

1. 将 P2 SQLite 存储升级为正式 PostgreSQL/账号权限模型，补多教师、多学校和审计查询。
2. 清洗 P3 知识图谱：把 283 个 AI 细粒度知识点合并、去重、对齐正式课程标准。
3. 将大模型 API 仅通过环境变量配置：`CAMPUS_LLM_API_KEY`、`CAMPUS_LLM_BASE_URL`、`CAMPUS_LLM_MODEL`，不要提交真实 key；当前知识点候选、引导讲解和变式题接口已支持这些变量，`scripts/llm_config_smoke.py` 已覆盖配置状态和 key 不回显检查，`scripts/llm_live_smoke.py --require` 可作为部署前真实模型连通性门禁。
4. 继续统一教师端、题库端、学生端前端入口，保留当前 P2 页面作为客户主工作台；当前已有客户化产品导航、会话权限状态、受控模式最小 RBAC 拦截、学生端独立练习页、错题上传、练习进度、练习历史检索和个人学习报告，下一步做正式账号目录和 SSO 接入。
5. 把 P1 Word/PDF/图片解析和学生错题识别升级为生产级异步任务队列；当前 Word、成绩、知识点、错题识别、引导讲解和变式题本地接口已跑通，PDF/图片仍待优化。
