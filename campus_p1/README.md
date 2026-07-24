# Word 切题系统

一套面向初中数学的智能试卷处理平台，把 `.docx` 试卷转换为结构化 JSON，并借助本地大模型自动标注知识点，生成教学反馈报告。

---

## 功能概览

| 流程 | 输入 | 输出 |
|------|------|------|
| **切题** | `.docx` 数学试卷 | `paper.v0.1` JSON（题干、选项、答案、公式、图片） |
| **知识点标注** | paper JSON | 每道题的 `qwen_analysis`（知识点、推理、置信度） |
| **教学反馈报告** | paper JSON + 教师阅卷 Excel | 错误率统计 / 薄弱知识点分析 / 教学建议（Markdown / Word / PDF） |

---

## 项目结构

```
word_cutter_system/
├── word_cutter_system/               # 核心 Python 库（可 pip install）
│   ├── campus_p2_core/
│   │   ├── contracts/                 # paper.v0.1 JSON Schema（Pydantic）
│   │   ├── p1_input/                 # DOCX 切题引擎
│   │   └── p2_stage_5/               # Qwen 知识点提取客户端
│   ├── scripts/                       # 命令行工具
│   └── examples/                      # 示例输入/输出
│
├── web_app/                          # Flask Web 应用
│   ├── frontend/
│   │   └── index.html                # 单页应用（试卷上传、编辑、AI 标注、报告生成）
│   └── backend/
│       ├── app.py                    # Flask 服务器，所有 API 路由
│       ├── papers/                    # 上传试卷存储
│       │   └── <paper_name>/
│       │       ├── paper.json
│       │       ├── assets/
│       │       └── feedback/         # 生成的反馈报告
│       └── feedback/                  # 教学反馈报告模块
│           ├── schema.py              # Excel 阅卷数据解析
│           ├── report_builder.py      # 报告构建编排
│           ├── template_render.py     # Jinja2 → Markdown / Word / PDF
│           ├── llm_report.py          # Qwen 生成教学分析和建议
│           └── templates/             # 报告模板
│
├── scripts/                           # 顶层脚本（独立于 word_cutter_system）
│   └── gen_class_exam_stats.py       # 生成模拟阅卷 Excel（用于演示）
│
├── requirements.txt                   # 全项目依赖
└── README.md                          # 本文件
```

---

## 环境要求

### 硬件

- **GPU**：CUDA 可用，推荐 8 GB+ 显存（运行 Qwen 模型）
- **内存**：16 GB+
- **磁盘**：10 GB+（50 套试卷示例约 500 MB）

### 软件

- Python 3.10+
- CUDA 12.x + cuDNN
- **大模型环境**（见下方"大模型"章节）

### 安装依赖

```bash
# 创建并激活 conda 环境（使用已有环境）
conda activate /home/dataset/yjk_data/conda_envs/paddleocr-vl

# 安装项目依赖
pip install -r requirements.txt

# 仅安装核心库（不含 Web / 报告模块）
pip install -r word_cutter_system/requirements.txt
```

---

## 大模型

本系统使用单一本地大模型，**不依赖任何云服务或 API Key**。

### 模型信息

| 项目 | 内容 |
|------|------|
| **模型名称** | Qwen2.5（推荐 Qwen2.5-3B-Instruct 及以上） |
| **模型路径** | `/home/dataset/yjk_data/Qwen` |
| **推理设备** | CUDA（默认 `cuda:2`，可通过 `QWEN_DEVICE` 环境变量修改） |
| **量化精度** | BF16 |
| **调用方式** | HuggingFace `transformers` `AutoModelForCausalLM` |
| **聊天模板** | Qwen2 Chat Template |

### 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `QWEN_MODEL_PATH` | `/home/dataset/yjk_data/Qwen` | 模型目录 |
| `QWEN_DEVICE` | `cuda:2` | 推理 GPU |
| `QWEN_MAX_NEW_TOKENS` | `512` | 最大生成长度 |
| `QWEN_TEMPERATURE` | `0.3` | 采样温度 |
| `QWEN_TOP_P` | `0.9` | Nucleus 采样 |

### 模型用途

1. **知识点提取**（`campus_p2_core/p2_stage_5/knowledge_extractor.py`）
   - 输入：题目题干、类型、选项
   - 输出：知识点列表、推理过程、置信度
   - 存储位置：`paper.json` → 每题 `qwen_analysis` 字段

2. **教学分析生成**（`web_app/backend/feedback/llm_report.py`）
   - 输入：全班错误率、各题知识点分布
   - 输出：薄弱知识点分析、教学建议
   - 存储位置：反馈报告 Markdown/Word/PDF 的"Llm分析"章节

---

## 快速开始

### 方式一：Web 应用（推荐）

```bash
cd web_app/backend
python app.py
# 打开浏览器访问 http://localhost:5000
```

Web 应用支持：
- 上传 `.docx` 试卷，自动切题 + AI 知识点标注
- 可视化编辑题目（题干、选项、答案、知识点）
- 上传阅卷 Excel，生成教学反馈报告（Markdown / Word / PDF）

### 方式二：命令行切题

```bash
# 切题（仅切题，不含 AI 标注）
python word_cutter_system/scripts/cut_word_papers.py \
    word_cutter_system/examples/input/2025年海南省中考数学试卷.docx \
    --out /tmp/output_single

# 端到端（切题 + AI 标注）
python word_cutter_system/scripts/pipeline.py \
    word_cutter_system/examples/input/ \
    --out /tmp/output_batch

# 仅对已有 JSON 做批量 AI 标注
python word_cutter_system/scripts/run_qwen_knowledge.py \
    --papers-dir web_app/backend/papers \
    --force          # 强制重跑（不加则跳过已有 ok 的题）
```

---

## paper.v0.1 JSON 结构

每道题的核心字段：

```json
{
  "question_id": "2025_000fc7a7_q001",
  "question_no": "1",
  "question_type": "single_choice",
  "stem_text": "下列运算中，正确的是（ ）",
  "stem_markdown": "下列运算中，正确的是（ ）",
  "options": [
    { "label": "A", "text": "$m^{3}+m^{3}＝2m^{3}$" },
    { "label": "B", "text": "$m^{3}+m^{3}＝m^{6}$" }
  ],
  "answer": "A",
  "solution": "【分析】...",
  "full_score": 4,
  "images": [],
  "qwen_analysis": {
    "knowledge_points": ["合并同类项", "同底数幂乘法", "幂的乘方"],
    "reasoning": "题目要求判断四个运算是否正确...",
    "confidence": 0.95,
    "model": "/home/dataset/yjk_data/Qwen",
    "status": "ok"
  },
  "parse_confidence": "high",
  "needs_review": false
}
```

---

## 教学反馈报告

教师上传 Excel 格式的阅卷统计数据（每题得分/错误人数），系统自动：

1. 解析 Excel，计算每题错误率、平均分、标准差
2. 将错误率与 AI 标注的知识点关联
3. 调用 Qwen 生成薄弱知识点分析和教学建议
4. 渲染 Markdown / Word / PDF 报告

报告包含：整体统计 → 各题错误率 → 薄弱 TOP 5 → 分类型分析 → AI 教学建议

---

## 技术亮点

- **零依赖外部服务**：纯本地推理，无 OpenAI、无 API Key
- **DOCX 直解析**：直接读 OOXML zip，无需 Word/LibreOffice/OCR
- **统一 Block 抽象**：段落和表格统一为 Block 序列，降低混排复杂度
- **答案区截断**：自动识别"参考答案"分隔，回填答案和解析
- **公式双向转换**：OMML → LaTeX，正文上标/下标 → `m³`/`y₁`
- **防误切策略**：解答题中的 A/B/C/D 不会被误切成选择题选项

---

## 当前边界

- 仅支持 `.docx`，不支持 PDF / 图片扫描卷
- 图形题 OCR 部分依赖上游预处理（非本系统职责）
- 表格输出为 Markdown，后续可扩展结构化 table schema
