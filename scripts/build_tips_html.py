#!/usr/bin/env python3
"""Build TIPS_TRICKS.html from TIPS_TRICKS.md while preserving styling.

This script:
- Reads the existing TIPS_TRICKS.html to reuse its <head> (CSS/theme, meta)
- Converts TIPS_TRICKS.md to HTML (no external deps; graceful fallback)
- Generates a simple index nav from H2 headings
- Wraps each H2 block into a <section> to match the current layout

Usage:
  python scripts/build_tips_html.py

Outputs:
  Overwrites ./TIPS_TRICKS.html in place.
"""

from __future__ import annotations

import io
import os
import re
import sys
from typing import List, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MD_PATH = os.path.join(ROOT, "TIPS_TRICKS.md")
HTML_PATH = os.path.join(ROOT, "TIPS_TRICKS.html")


def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def write_text(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def html_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def slugify(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"[^a-z0-9\-]", "", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text or "section"


def replace_inline(md: str) -> str:
    # Inline code: `code`
    md = re.sub(r"`([^`]+)`", lambda m: f"<code>{html_escape(m.group(1))}</code>", md)

    # Links: [text](url)
    def _link(m: re.Match[str]) -> str:
        text, url = m.group(1), m.group(2)
        return f'<a href="{html_escape(url)}">{html_escape(text)}</a>'

    md = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", _link, md)
    return md


def md_to_sections(md: str) -> tuple[str, list[tuple[str, str, str]]]:
    """Very small Markdown-to-HTML for this document.

    Returns (title, sections), where sections is a list of (id, h2_title, html_content).
    Any content before the first H2 is included as a section with an empty title.
    """
    lines = md.splitlines()
    title = "Tips & Tricks"
    sections: list[tuple[str, str, str]] = []
    buf: list[str] = []
    cur_id = "intro"
    cur_h2 = ""
    in_code = False
    code_buf: list[str] = []
    ul_open = False
    p_open = False

    def flush_para():
        nonlocal p_open
        if p_open:
            buf.append("</p>")
            p_open = False

    def flush_ul():
        nonlocal ul_open
        if ul_open:
            buf.append("</ul>")
            ul_open = False

    def flush_section():
        nonlocal buf, cur_id, cur_h2
        if not buf and not cur_h2:
            return
        sections.append((cur_id, cur_h2, "\n".join(buf).strip()))
        buf = []

    for raw in lines:
        line = raw.rstrip("\n")
        # Fenced code blocks
        if line.strip().startswith("```"):
            if in_code:
                # close block
                code_html = "\n".join(html_escape(x) for x in code_buf)
                buf.append(f"<pre>\n<code>{code_html}\n</code>\n</pre>")
                code_buf = []
                in_code = False
            else:
                flush_para()
                flush_ul()
                in_code = True
            continue

        if in_code:
            code_buf.append(line)
            continue

        # Headings
        m1 = re.match(r"^#\s+(.+)$", line)
        if m1:
            title = m1.group(1).strip()
            continue

        m2 = re.match(r"^##\s+(.+)$", line)
        if m2:
            flush_para()
            flush_ul()
            flush_section()
            cur_h2 = m2.group(1).strip()
            cur_id = slugify(cur_h2)
            buf.append(f'<h2 id="{cur_id}">{html_escape(cur_h2)}</h2>')
            continue

        m3 = re.match(r"^###\s+(.+)$", line)
        if m3:
            flush_para()
            flush_ul()
            h3 = m3.group(1).strip()
            h3_id = slugify(h3)
            buf.append(f'<h3 id="{h3_id}">{html_escape(h3)}</h3>')
            continue

        # Lists
        if re.match(r"^\s*[-*]\s+", line):
            if not ul_open:
                flush_para()
                buf.append("<ul>")
                ul_open = True
            item = re.sub(r"^\s*[-*]\s+", "", line)
            buf.append(f"<li>{replace_inline(html_escape(item))}</li>")
            continue
        else:
            flush_ul()

        # Paragraphs and blank lines
        if not line.strip():
            flush_para()
            continue
        if not p_open:
            buf.append("<p>")
            p_open = True
        buf.append(replace_inline(html_escape(line)))

    # Flush pending constructs
    if in_code:
        code_html = "\n".join(html_escape(x) for x in code_buf)
        buf.append(f"<pre>\n<code>{code_html}\n</code>\n</pre>")
    flush_para()
    flush_ul()
    flush_section()

    return title, sections


def build_nav(sections: list[tuple[str, str, str]]) -> str:
    items = []
    for sec_id, h2, _ in sections:
        label = h2 or "Intro"
        items.append(f'<li><a href="#{sec_id}"> - {html_escape(label)}</a></li>')
    return '<nav id="index">\n  <ul>\n    ' + "\n    ".join(items) + "\n  </ul>\n</nav>"


def wrap_sections(sections: list[tuple[str, str, str]]) -> str:
    parts = []
    for sec_id, h2, html in sections:
        # Ensure the first element of a section is its H2 (if not intro)
        content = html
        if h2 and not re.search(r"<h2[^>]*>", html):
            content = f'<h2 id="{sec_id}">{html_escape(h2)}</h2>\n' + html
        parts.append("<section>\n" + content + "\n</section>")
    return '<main class="container">\n' + "\n".join(parts) + "\n</main>"


def extract_head(html_text: str) -> str | None:
    m = re.search(r"(?s)<head>(.*?)</head>", html_text)
    return m.group(1) if m else None


def maybe_replace_title(head_html: str, new_title: str) -> str:
    if "<title" not in head_html:
        return head_html
    return re.sub(
        r"(?s)(<title[^>]*>)(.*?)(</title>)",
        lambda m: m.group(1) + html_escape(new_title) + m.group(3),
        head_html,
        count=1,
    )


def main() -> int:
    if not os.path.exists(MD_PATH):
        print(f"Missing {MD_PATH}", file=sys.stderr)
        return 2
    md_text = read_text(MD_PATH)
    title, sections = md_to_sections(md_text)

    # Try to reuse existing <head> for consistent styling
    head_inner = None
    if os.path.exists(HTML_PATH):
        try:
            head_inner = extract_head(read_text(HTML_PATH))
        except Exception:
            head_inner = None

    if not head_inner:
        # Fallback minimal head with current theme (mirrors existing file)
        head_inner = """
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <title>Tips & Tricks</title>
  <style>
    :root{--nord0:#2E3440;--nord1:#3B4252;--nord2:#434C5E;--nord3:#4C566A;--nord4:#D8DEE9;--nord8:#88C0D0}
    body{background-color:var(--nord0);color:var(--nord4);font-family:system-ui,sans-serif;line-height:1.6;margin:0;padding:2rem}
    h1,h2,h3{border-bottom:1px solid var(--nord3);padding-bottom:.3rem}
    pre{background:var(--nord1);color:var(--nord4);padding:1rem;border-radius:4px;white-space:pre-wrap;word-break:break-word}
    code{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;background:var(--nord2);color:var(--nord4);padding:.2rem .4rem;border-radius:4px}
    pre code{background:transparent;padding:0;display:block;border-radius:0}
    a{color:var(--nord8)}
    .container{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:1.5rem}
    nav#index{margin:1rem 0 2rem}
    nav#index ul{list-style:none;padding:0;display:flex;flex-wrap:wrap;gap:1rem}
    nav#index a{color:var(--nord8);text-decoration:none}
    section{background:var(--nord1);padding:1rem;border-radius:8px}
  </style>
        """.strip("\n")

    head_inner = maybe_replace_title(head_inner, title)

    # Build body
    h1_html = f"<h1>{html_escape(title)}</h1>"
    nav_html = build_nav(sections)
    main_html = wrap_sections(sections)

    out = (
        '<!DOCTYPE html>\n<html lang="en">\n\n<head>\n'
        + head_inner
        + "\n</head>\n\n<body>\n"
        + h1_html
        + "\n"
        + nav_html
        + "\n"
        + main_html
        + "\n</body>\n\n</html>\n"
    )

    write_text(HTML_PATH, out)
    print(f"Wrote {HTML_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
