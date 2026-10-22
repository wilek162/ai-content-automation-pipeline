"""Safe portable Markdown rendering; raw HTML and active links are disabled."""

from html import escape
import re
from markdown_it import MarkdownIt


def render(markdown):
    markdown = re.sub(r"\[\[claim:[A-Za-z0-9_-]+\]\]", "", markdown)
    return MarkdownIt("commonmark", {"html": False, "linkify": False}).render(markdown)


def preview(title, markdown, report):
    return (
        "<!doctype html><html lang='en'><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<meta http-equiv='Content-Security-Policy' content=\"default-src 'none'; style-src 'unsafe-inline'\">"
        f"<title>{escape(title)}</title><style>body{{max-width:760px;margin:3rem auto;padding:0 1rem;"
        "font:18px/1.65 system-ui;color:#182436}}pre{overflow:auto}a{color:#1558a6}</style>"
        f"<body><p>Technical checks: {escape(report['status'])}. Human review required.</p>"
        + render(markdown)
        + "</body></html>"
    )
