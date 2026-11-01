"""把 Markdown 笔记转成符合 docx 转换规范的 HTML（零依赖，仅标准库）。

针对本项目笔记的语法子集：标题(h1-h6)、表格、```代码块、> 引用、- / 1. 列表
（支持两级缩进）、**粗体**、`行内代码`、--- 分隔线。

用法：
    python src/md2html_note.py "docs/phase3_自查笔记.md" "docs/phase3_自查笔记.html"
"""
import html
import re
import sys
from pathlib import Path

CSS = """
body{font-family:"宋体",SimSun,serif;font-size:12pt;line-height:1.75;color:#222;}
h1{font-size:18pt;text-align:center;margin:0 0 14pt 0;}
h2{font-size:15pt;margin:18pt 0 8pt 0;border-bottom:1px solid #ddd;padding-bottom:4pt;}
h3{font-size:13pt;margin:14pt 0 6pt 0;}
h4{font-size:12pt;margin:12pt 0 6pt 0;}
p{margin:6pt 0;text-align:justify;}
table{border-collapse:collapse;width:100%;margin:8pt 0;font-size:10.5pt;}
th,td{border:1px solid #999;padding:4pt 6pt;vertical-align:top;}
th{background:#f0f0f0;font-weight:bold;}
code{font-family:Consolas,"Courier New",monospace;background:#f4f4f4;font-size:9.5pt;}
pre{background:#f6f8fa;border:1px solid #e1e4e8;padding:8pt;font-family:Consolas,"Courier New",monospace;font-size:9pt;line-height:1.45;white-space:pre-wrap;}
blockquote{border-left:3pt solid #bbb;margin:8pt 0;padding:4pt 10pt;background:#fafafa;color:#333;}
hr{border:none;border-top:1px solid #ccc;margin:14pt 0;}
ul,ol{margin:6pt 0 6pt 20pt;padding:0;}
li{margin:3pt 0;}
"""


def inline(s: str) -> str:
    s = html.escape(s, quote=False)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    return s


def split_row(line: str):
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def render_table(header, rows) -> str:
    th = "".join(f"<th>{inline(c)}</th>" for c in header)
    body = []
    for r in rows:
        cells = (r + [""] * len(header))[: len(header)]
        body.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in cells) + "</tr>")
    return (
        "<table><thead><tr>" + th + "</tr></thead><tbody>"
        + "".join(body) + "</tbody></table>"
    )


def build_list(items) -> str:
    """items: [(level, ordered, text)]。

    只做「一级列表 + 该项内换行缩进」的稳妥渲染：子项不生成嵌套 <ul>，
    而是作为父 <li> 内的 <br/>+全角缩进行。这样不会产生非法嵌套，
    Word 引擎渲染更可靠。
    """
    out, cur_tag, li_open = [], None, False
    for level, ordered, text in items:
        tag = "ol" if ordered else "ul"
        if level == 0:
            if li_open:
                out.append("</li>")
                li_open = False
            if cur_tag != tag:
                if cur_tag:
                    out.append(f"</{cur_tag}>")
                out.append(f"<{tag}>")
                cur_tag = tag
            out.append(f"<li>{inline(text)}")
            li_open = True
        else:
            if li_open:
                out.append("<br/>　　· " + inline(text))
            else:
                if cur_tag != tag:
                    if cur_tag:
                        out.append(f"</{cur_tag}>")
                    out.append(f"<{tag}>")
                    cur_tag = tag
                out.append(f"<li>{inline(text)}</li>")
    if li_open:
        out.append("</li>")
    if cur_tag:
        out.append(f"</{cur_tag}>")
    return "".join(out)


def convert(md: str) -> str:
    lines = md.split("\n")
    out, i, n = [], 0, len(lines)
    list_items = []

    def flush_list():
        nonlocal list_items
        if list_items:
            out.append(build_list(list_items))
            list_items = []

    while i < n:
        line = lines[i]

        # 代码块
        if line.strip().startswith("```"):
            flush_list()
            i += 1
            code = []
            while i < n and not lines[i].strip().startswith("```"):
                code.append(lines[i])
                i += 1
            i += 1
            out.append("<pre><code>" + html.escape("\n".join(code)) + "</code></pre>")
            continue

        # 标题
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            flush_list()
            lv = len(m.group(1))
            out.append(f"<h{lv}>{inline(m.group(2).strip())}</h{lv}>")
            i += 1
            continue

        # 分隔线
        if re.match(r"^\s*---+\s*$", line):
            flush_list()
            out.append("<hr/>")
            i += 1
            continue

        # 表格
        if line.strip().startswith("|") and i + 1 < n and re.match(
            r"^\s*\|[\s:\-\|]+\|\s*$", lines[i + 1]
        ):
            flush_list()
            header = split_row(line)
            i += 2
            rows = []
            while i < n and lines[i].strip().startswith("|"):
                rows.append(split_row(lines[i]))
                i += 1
            out.append(render_table(header, rows))
            continue

        # 引用
        if line.strip().startswith(">"):
            flush_list()
            q = []
            while i < n and lines[i].strip().startswith(">"):
                q.append(re.sub(r"^\s*>\s?", "", lines[i]))
                i += 1
            q = [x for x in q if x.strip()]
            out.append("<blockquote>" + "<br/>".join(inline(x) for x in q) + "</blockquote>")
            continue

        # 列表
        m = re.match(r"^(\s*)([-*]|\d+\.)\s+(.*)$", line)
        if m:
            indent = len(m.group(1))
            level = 1 if indent >= 2 else 0
            ordered = bool(re.match(r"\d", m.group(2)))
            list_items.append((level, ordered, m.group(3)))
            i += 1
            continue

        # 空行
        if not line.strip():
            flush_list()
            i += 1
            continue

        # 段落
        flush_list()
        para = [line]
        i += 1
        while (
            i < n
            and lines[i].strip()
            and not re.match(r"^(#{1,6}\s|\s*[-*]\s|\s*\d+\.\s|>|\|)", lines[i])
            and not lines[i].strip().startswith("```")
            and not re.match(r"^\s*---+\s*$", lines[i])
        ):
            para.append(lines[i])
            i += 1
        out.append("<p>" + inline(" ".join(x.strip() for x in para)) + "</p>")

    flush_list()
    return "\n".join(out)


def main():
    if len(sys.argv) < 3:
        raise SystemExit('用法: python src/md2html_note.py "in.md" "out.html"')
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    md = src.read_text(encoding="utf-8")
    body = convert(md)
    page = (
        '<!DOCTYPE html><html><head><meta charset="utf-8"><style>'
        + CSS
        + "</style></head><body>"
        + body
        + "</body></html>"
    )
    dst.write_text(page, encoding="utf-8")
    print(f"OK: {dst}  ({len(page)} chars, {body.count('<table')} 表, "
          f"{body.count('<pre>')} 代码块)")


if __name__ == "__main__":
    main()
