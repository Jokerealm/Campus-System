# Word 切题系统

本工程是一个独立整理版的 Word 切题系统，用于把 `.docx` 数学试卷转换为规整的 `paper.v0.1 JSON`。

当前版本只处理 Word `.docx`，暂不处理 PDF/OCR。

## 目录结构

```text
word_cutter_system/
  campus_p2_core/
    contracts/paper.py                 # paper.v0.1 输出契约
    p1_input/normalized_paper.py        # JSON 校验入口
    p1_input/word_cutter.py             # 切题核心
  scripts/
    cut_word_papers.py                  # 批量/单文件切题命令
    validate_normalized_paper.py        # 输出 JSON 校验命令
    check_examples.py                   # 示例回归检查
  examples/
    input/                              # 示例 Word 输入
    output/                             # 示例输出 JSON + 图片 assets
    summary/full_batch_summary.json     # 50 套全量处理摘要
  requirements.txt
```

## 快速开始

Windows PowerShell：

```powershell
cd word_cutter_system
python -m pip install -r requirements.txt
python scripts\cut_word_papers.py examples\input --out examples\output_rebuild
```

校验示例输出：

```powershell
python scripts\check_examples.py
python scripts\validate_normalized_paper.py examples\output\2025_01b4925d\paper.json
```

处理单个 Word：

```powershell
python scripts\cut_word_papers.py examples\input\2025年海南省中考数学试卷.docx --out output_single
```

处理一个目录：

```powershell
python scripts\cut_word_papers.py <试卷目录> --out <输出目录>
```

处理 zip：

```powershell
python scripts\cut_word_papers.py <试卷压缩包.zip> --out <输出目录>
```

## 输出格式

每套试卷输出为：

```text
<输出目录>/
  <paper_id>/
    paper.json
    assets/
      <paper_id>_q001_img01.png
      ...
```

`paper.json` 使用 `paper.v0.1` 结构，关键字段包括：

- `question_no`：题号。
- `question_type`：`single_choice`、`multiple_choice`、`blank`、`solution`。
- `stem_text`：纯文本题干，便于检索。
- `stem_markdown`：带公式、图片和表格的题干。
- `options`：选择题选项。
- `answer` / `solution`：从参考答案区回填的答案和解析。
- `full_score`：从 `（x分）` 中提取的满分。
- `images`：题目图片引用，路径相对 `paper.json` 所在目录。
- `parse_confidence` / `needs_review`：切题置信度和人工复核标记。

## 技术路线

### 1. 直接解析 DOCX / OOXML

`.docx` 本质是 zip 包。系统直接读取：

- `word/document.xml`：正文段落、表格、公式、图片占位。
- `word/_rels/document.xml.rels`：图片关系 `rId -> media/...`。
- `word/media/*`：内嵌图片文件。

这样不依赖 Microsoft Word、LibreOffice 或 OCR，速度快、成本低，适合格式相对统一的 Word 试卷。

### 2. 段落和表格统一成 Block

系统先把 Word 正文中的 `w:p` 段落和 `w:tbl` 表格统一抽成 `Block`：

- `text`：纯文本。
- `markdown`：带公式、图片、表格的 Markdown。
- `image_refs`：图片引用。
- `formula_count`：公式标记数量。

后续切题只面对统一 Block 序列，降低段落、表格、图片混排带来的复杂度。

### 3. 题号连续性切题

题号识别支持：

- `1．（4分）`
- `1.`
- `1、`
- `（多选）7．`

同时要求题号连续，避免把解答题内部步骤误切成新题。例如 `（1）求...`、`1．测出...` 不会轻易成为一道新题。

### 4. 答案区截断与答案回填

很多试卷前半部分是正式试卷，后半部分是“参考答案与试题解析”。系统会：

1. 识别“参考答案”“答案与试题解析”等答案区标题。
2. 正式试卷区用于生成题目。
3. 答案解析区再次按题号切分。
4. 将 `answer` 和 `solution` 回填到对应题目。

### 5. 公式和正文数学语义识别

系统同时处理两类数学表达：

一类是真公式 OMML，例如分式、根号、上下标、向量、方程组：

```text
OMML fraction -> \frac{a}{b}
OMML radical  -> \sqrt{x}
OMML vector   -> \overrightarrow{AB}
```

另一类是 Word 正文 run 样式，例如普通字符加上标/下标：

```text
m + 上标 3 -> stem_text: m³
m + 上标 3 -> stem_markdown: m^{3}
y + 下标 1 -> stem_text: y₁
y + 下标 1 -> stem_markdown: y_{1}
```

还会对跨文本和公式对象的片段做后处理，例如：

```text
|2-\sqrt{5}| -> $|2-\sqrt{5}|$
AB→          -> \overrightarrow{AB}
(m³)³        -> $(m^{3})^{3}$
```

### 6. 图片抽取和定位

系统会读取图片关系，把内嵌图片导出到 `assets/`，并在题干中插入：

```markdown
![2025_01b4925d_q019_img01](assets/2025_01b4925d_q019_img01.png)
```

对于图形选项，会尽量标注为：

```json
{"role": "option_A"}
```

题干图、统计图、几何图默认标注为 `stem`。

### 7. 表格提取

Word 真表格 `w:tbl` 会输出为标准 Markdown 表格。例如海南卷第 19 题：

```markdown
| 分数段 | 等次 | 人数 |
| --- | --- | --- |
| 90≤x≤100 | A | a |
| 80≤x＜90 | B | 6 |
| 70≤x＜80 | C | 6 |
| 60≤x＜70 | D | b |
| 0≤x＜60 | E | 2 |
```

### 8. 防误切策略

数学题干里经常出现 `A、B、C、D`，例如“划分为 A、B、C、D、E 五个等次”。系统做了约束：

- 只有选择题/多选题章节才默认切选项。
- 解答题和填空题默认不切选项。
- 选项优先识别 `A．/A.`，并要求从 A 开始形成连续序列。

这解决了海南卷第 19 题题干被截断的问题。

### 9. 特殊符号处理

系统会保留普通文本中的特殊符号，例如：

```text
▲
★
△
∠
⊙
≤
≥
≠
```

对于 Word `w:sym` 形式的符号，也做了常见映射兜底。

## 示例说明

### 示例 1：上海卷

输入：

```text
examples/input/2025年上海市中考数学试卷.docx
```

输出：

```text
examples/output/2025_000fc7a7/paper.json
```

覆盖能力：

- 幂和次方：`m³ -> m^{3}`
- 括号整体幂：`(m³)³ -> $(m^{3})^{3}$`
- 向量：`AB→ -> \overrightarrow{AB}`
- 绝对值：`|2-\sqrt{5}|`
- 题目图片抽取

示例输出片段：

```text
A:$m^{3}+m^{3}＝2m^{3}$
D:$(m^{3})^{3}＝m^{6}$
在正方形ABCD中，$|\overrightarrow{AB}+\overrightarrow{BC}|$：$|\overrightarrow{CD}|$的值是（ ）
计算：$\frac{4}{\sqrt{5}+1}-20^{\frac{1}{2}}+|2-\sqrt{5}|+((\frac{1}{2}))^{-3}$．
```

### 示例 2：海南卷

输入：

```text
examples/input/2025年海南省中考数学试卷.docx
```

输出：

```text
examples/output/2025_01b4925d/paper.json
```

覆盖能力：

- 表格提取
- `▲`、`★` 特殊符号保留
- `A、B、C、D、E` 等次不误切成选择题选项
- 统计图图片抽取

示例输出片段：

```text
划分为A、B、C、D、E五个等次
54，71，57，▲，65，67，...，★，92，94．

| 分数段 | 等次 | 人数 |
| --- | --- | --- |
| 90≤x≤100 | A | a |
| 80≤x＜90 | B | 6 |
```

## 当前全量效果

对本地 `2025中考数学真题卷` 的 50 套 `.docx` 批量处理结果：

```text
试卷数：50
题目数：1248
图片数：951
公式标记数：8877
needs_review_questions：0
paper.v0.1 校验：通过
题量范围：18 到 28 题/套
```

摘要文件：

```text
examples/summary/full_batch_summary.json
```

## 当前边界

- 只支持 `.docx`，暂不支持 PDF。
- 对扫描版、图片版试卷不做 OCR。
- 对极复杂 WordArt、浮动文本框、手绘组合图形只做尽力提取。
- 知识点 `knowledge_candidates` 暂为空，后续可接大模型或知识库自动标注。
- 表格目前输出 Markdown，若后续前端需要精确单元格合并、行列跨度，需要扩展结构化 table schema。
