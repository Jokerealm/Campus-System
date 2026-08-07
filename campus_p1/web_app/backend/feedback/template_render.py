"""教学反馈报告模板渲染：jinja2 (Markdown) + docxtpl (Word)。"""
from __future__ import annotations

import re
from io import BytesIO
from pathlib import Path

from docxtpl import DocxTemplate
from jinja2 import Environment, FileSystemLoader, StrictUndefined


def render_markdown(template_path: str, context: dict) -> str:
    """渲染 jinja2 Markdown 模板。"""
    p = Path(template_path)
    env = Environment(
        loader=FileSystemLoader(str(p.parent)),
        autoescape=False,
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )
    tpl = env.get_template(p.name)
    return tpl.render(**context)


def render_docx(template_path: str, context: dict) -> bytes:
    """渲染 docxtpl 模板，返回 .docx 字节流。"""
    tpl = DocxTemplate(template_path)
    tpl.render(context)
    buf = BytesIO()
    tpl.docx.save(buf)
    return buf.getvalue()


# ---- markdown -> html（用于 pdf 导出） ------------------------------------

def _md_table_to_html(md: str) -> str:
    """把 GFM 风格的 markdown 表格转换为 <table>（最小实现）。"""
    lines = md.splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if "|" in line and i + 1 < len(lines) and re.match(r"^\s*\|?\s*:?-{2,}", lines[i + 1]):
            rows = []
            while i < len(lines) and "|" in lines[i]:
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                rows.append(cells)
                i += 1
            # 第 1 行表头 / 第 2 行分隔
            if len(rows) >= 2:
                header = rows[0]
                body = rows[2:] if len(rows) >= 3 else []
                out.append("<table>")
                out.append("<thead><tr>" + "".join(f"<th>{c}</th>" for c in header) + "</tr></thead>")
                out.append("<tbody>")
                for r in body:
                    out.append("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>")
                out.append("</tbody></table>")
            continue
        out.append(line)
        i += 1
    return "\n".join(out)


def markdown_to_html(md: str) -> str:
    """轻量级 md -> html：标题/粗体/列表/代码/表格。

    不依赖外部 markdown 库（weasyprint 路径中避免重复依赖冲突）。
    """
    html = _md_table_to_html(md)

    # 标题
    html = re.sub(r"^###### (.*)$", r"<h6>\1</h6>", html, flags=re.M)
    html = re.sub(r"^##### (.*)$", r"<h5>\1</h5>", html, flags=re.M)
    html = re.sub(r"^#### (.*)$", r"<h4>\1</h4>", html, flags=re.M)
    html = re.sub(r"^### (.*)$", r"<h3>\1</h3>", html, flags=re.M)
    html = re.sub(r"^## (.*)$", r"<h2>\1</h2>", html, flags=re.M)
    html = re.sub(r"^# (.*)$", r"<h1>\1</h1>", html, flags=re.M)

    # 引用
    html = re.sub(r"^> (.*)$", r"<blockquote>\1</blockquote>", html, flags=re.M)

    # 粗体 + 斜体
    html = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html)
    html = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<em>\1</em>", html)

    # 行内代码
    html = re.sub(r"`([^`]+)`", r"<code>\1</code>", html)

    # 无序列表
    html = re.sub(r"(?:^- .+(?:\n|$))+", lambda m: "<ul>" + "".join(f"<li>{x[2:]}</li>" for x in m.group(0).strip().split("\n")) + "</ul>", html, flags=re.M)
    _ol_re = re.compile(r"^\d+\. ")
    def _ol_sub(m):
        items = []
        for x in m.group(0).strip().split("\n"):
            items.append("<li>" + _ol_re.sub("", x) + "</li>")
        return "<ol>" + "".join(items) + "</ol>"
    html = re.sub(r"(?:^\d+\. .+(?:\n|$))+", _ol_sub, html, flags=re.M)

    # 段落：把空行分隔的连续行包成 <p>
    blocks: list[str] = []
    para: list[str] = []
    for line in html.splitlines():
        s = line.strip()
        if not s:
            if para:
                blocks.append("<p>" + " ".join(para) + "</p>")
                para = []
        elif s.startswith("<") and s.endswith(">"):
            if para:
                blocks.append("<p>" + " ".join(para) + "</p>")
                para = []
            blocks.append(s)
        else:
            para.append(s)
    if para:
        blocks.append("<p>" + " ".join(para) + "</p>")
    return "\n".join(blocks)


def html_to_pdf(html: str, base_url: str | None = None) -> bytes:
    """weasyprint -> pdf bytes。"""
    from weasyprint import HTML
    return HTML(string=html, base_url=base_url).write_pdf()
