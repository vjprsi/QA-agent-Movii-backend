#!/usr/bin/env python3
"""Render QA-REPORT.md → QA-REPORT.html (self-contained, printable). Uses `markdown` if installed, else a minimal converter."""
import html
import re
import sys
import os

CSS = """body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:1100px;margin:32px auto;padding:0 16px;color:#222;line-height:1.45}
table{border-collapse:collapse;width:100%;margin:12px 0;font-size:14px}th,td{border:1px solid #ccc;padding:6px 8px;vertical-align:top}
th{background:#f3f3f3;text-align:left}code,pre{background:#f6f8fa;border-radius:4px;padding:2px 4px;font-size:13px}pre{padding:10px;overflow:auto}
h1{border-bottom:2px solid #333}h2{border-bottom:1px solid #ccc;margin-top:28px}
.CRITICAL{color:#fff;background:#b71c1c;padding:1px 6px;border-radius:3px}.HIGH{color:#fff;background:#e65100;padding:1px 6px;border-radius:3px}
.MEDIUM{background:#fdd835;padding:1px 6px;border-radius:3px}.LOW{background:#c8e6c9;padding:1px 6px;border-radius:3px}
.PASS{color:#1b5e20;font-weight:600}.FAIL{color:#b71c1c;font-weight:600}.BLOCKED,.UNVERIFIED{color:#6a1b9a;font-weight:600}
@media print{body{max-width:none}a{color:inherit;text-decoration:none}}"""


def minimal_md(md):
    out, in_code, in_table, in_list = [], False, False, False
    for line in md.splitlines():
        if line.startswith("```"):
            in_code = not in_code; out.append("<pre>" if in_code else "</pre>"); continue
        if in_code:
            out.append(html.escape(line)); continue
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
                continue
            if not in_table:
                out.append("<table>"); in_table = True; out.append("<tr>" + "".join(f"<th>{inline(c)}</th>" for c in cells) + "</tr>"); continue
            out.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in cells) + "</tr>"); continue
        elif in_table:
            out.append("</table>"); in_table = False
        m = re.match(r"^(#{1,6})\s+(.*)", line)
        if m:
            out.append(f"<h{len(m.group(1))}>{inline(m.group(2))}</h{len(m.group(1))}>"); continue
        if re.match(r"^\s*[-*]\s+", line):
            if not in_list:
                out.append("<ul>"); in_list = True
            out.append(f"<li>{inline(re.sub(r'^\s*[-*]\s+', '', line))}</li>"); continue
        elif in_list:
            out.append("</ul>"); in_list = False
        if re.match(r"^\s*\d+\.\s+", line):
            out.append(f"<p>{inline(line)}</p>"); continue
        out.append(f"<p>{inline(line)}</p>" if line.strip() else "")
    if in_table: out.append("</table>")
    if in_list: out.append("</ul>")
    return "\n".join(out)


def inline(s):
    s = html.escape(s, quote=False)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', s)
    s = re.sub(r"\b(CRITICAL|HIGH|MEDIUM|LOW|PASS|FAIL|BLOCKED|UNVERIFIED)\b", r'<span class="\1">\1</span>', s)
    return s.replace("&lt;br&gt;", "<br>")


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "QA-REPORT.md"
    dst = sys.argv[2] if len(sys.argv) > 2 else os.path.splitext(src)[0] + ".html"
    md = open(src, encoding="utf-8").read()
    try:
        import markdown  # type: ignore
        body = markdown.markdown(md, extensions=["tables", "fenced_code"])
        body = re.sub(r"\b(CRITICAL|HIGH|MEDIUM|LOW|PASS|FAIL|BLOCKED|UNVERIFIED)\b", r'<span class="\1">\1</span>', body)
    except ImportError:
        body = minimal_md(md)
    title = re.search(r"^#\s+(.*)", md, re.M)
    open(dst, "w", encoding="utf-8").write(f"<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(title.group(1) if title else 'QA Report')}</title><style>{CSS}</style></head><body>{body}</body></html>")
    print(f"wrote {dst}")


if __name__ == "__main__":
    main()
