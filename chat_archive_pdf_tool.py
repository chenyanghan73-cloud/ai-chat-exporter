from __future__ import annotations

import argparse
import html
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import tkinter as tk
from tkinter import filedialog, messagebox, ttk


LOCAL_DEPS = Path(__file__).resolve().parent / ".deps"
if LOCAL_DEPS.exists():
    sys.path.insert(0, str(LOCAL_DEPS))

try:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import HRFlowable, Paragraph, Preformatted, SimpleDocTemplate, Spacer

    REPORTLAB_READY = True
    REPORTLAB_IMPORT_ERROR = ""
except Exception as exc:
    REPORTLAB_READY = False
    REPORTLAB_IMPORT_ERROR = str(exc)


APP_NAME = "AI 聊天记录导出 PDF"
OUTPUT_DIR = Path("output")
TMP_DIR = Path("tmp")
PDF_FONT_NAME = "ChatArchiveSans"
PDF_FONT_BOLD_NAME = "ChatArchiveSansBold"
TRANSCRIPT_ROLE_RE = re.compile(
    r"^\s*(用户|我|user|human|assistant|助手|chatgpt|claude|gemini|ai|系统|system|tool|工具)\s*[:：]\s*(.*)$",
    re.IGNORECASE,
)

BROWSER_CANDIDATES = [
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
]

ROLE_LABELS = {
    "user": "用户",
    "assistant": "助手",
    "system": "系统",
    "tool": "工具",
}

ROLE_STYLES = {
    "user": "user",
    "assistant": "assistant",
    "system": "system",
    "tool": "tool",
}


@dataclass
class Message:
    role: str
    content: str
    timestamp: float | None = None
    speaker: str = ""


@dataclass
class Conversation:
    title: str
    messages: list[Message] = field(default_factory=list)
    source: str = ""
    created_at: float | None = None


def normalize_role(value: str | None) -> str:
    text = (value or "").strip().lower()
    if text in {"user", "human", "我", "用户"}:
        return "user"
    if text in {"assistant", "chatgpt", "claude", "gemini", "ai", "bot", "助手"}:
        return "assistant"
    if text in {"system", "系统"}:
        return "system"
    if text in {"tool", "工具", "function"}:
        return "tool"
    return "assistant"


def format_timestamp(value: float | None) -> str:
    if not value:
        return ""
    try:
        return datetime.fromtimestamp(value).strftime("%Y-%m-%d %H:%M:%S")
    except (OverflowError, OSError, ValueError):
        return ""


def safe_filename(text: str, fallback: str = "chat-export") -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|]+", "_", (text or "").strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return cleaned[:80] or fallback


def find_browser() -> Path:
    for candidate in BROWSER_CANDIDATES:
        if candidate.exists():
            return candidate
    raise RuntimeError("未找到可用的 Edge/Chrome 浏览器，无法生成 PDF。")


def read_text_file(path: Path) -> str:
    encodings = ("utf-8", "utf-8-sig", "gb18030", "gbk")
    last_error: Exception | None = None
    for encoding in encodings:
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
    if last_error:
        raise last_error
    return path.read_text(encoding="utf-8")


def register_pdf_fonts() -> None:
    if not REPORTLAB_READY:
        raise RuntimeError(f"reportlab 不可用: {REPORTLAB_IMPORT_ERROR}")
    if PDF_FONT_NAME in pdfmetrics.getRegisteredFontNames():
        return

    regular_candidates = [
        Path(r"C:\Windows\Fonts\msyh.ttc"),
        Path(r"C:\Windows\Fonts\msyh.ttf"),
        Path(r"C:\Windows\Fonts\simsun.ttc"),
    ]
    bold_candidates = [
        Path(r"C:\Windows\Fonts\msyhbd.ttc"),
        Path(r"C:\Windows\Fonts\msyh.ttc"),
        Path(r"C:\Windows\Fonts\simsunb.ttf"),
    ]

    regular_font = next((path for path in regular_candidates if path.exists()), None)
    bold_font = next((path for path in bold_candidates if path.exists()), regular_font)
    if not regular_font or not bold_font:
        raise RuntimeError("未找到可用的中文字体文件，无法生成中文 PDF。")

    pdfmetrics.registerFont(TTFont(PDF_FONT_NAME, str(regular_font)))
    pdfmetrics.registerFont(TTFont(PDF_FONT_BOLD_NAME, str(bold_font)))


def extract_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        parts = [extract_text(item).strip() for item in value]
        return "\n".join(part for part in parts if part)
    if isinstance(value, dict):
        if value.get("content_type") in {"image_asset_pointer", "image"}:
            return "[图片]"
        if value.get("type") in {"image", "image_url"}:
            return "[图片]"

        ordered_keys = [
            "parts",
            "text",
            "content",
            "message",
            "value",
            "result",
            "output",
            "input",
            "caption",
            "title",
        ]
        fragments: list[str] = []
        for key in ordered_keys:
            if key in value:
                item = extract_text(value.get(key)).strip()
                if item and item not in fragments:
                    fragments.append(item)
        if fragments:
            return "\n".join(fragments)

        nested: list[str] = []
        for item in value.values():
            text = extract_text(item).strip()
            if text and text not in nested:
                nested.append(text)
        return "\n".join(nested)
    return str(value)


def parse_plain_transcript(text: str, title: str = "粘贴内容", source: str = "") -> list[Conversation]:
    text = text.replace("\r\n", "\n").strip()
    if not text:
        return []

    messages: list[Message] = []
    current_role: str | None = None
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_role, current_lines
        if current_role and any(line.strip() for line in current_lines):
            content = "\n".join(current_lines).strip()
            messages.append(Message(role=current_role, content=content))
        current_role = None
        current_lines = []

    for raw_line in text.split("\n"):
        match = TRANSCRIPT_ROLE_RE.match(raw_line)
        if match:
            flush()
            current_role = normalize_role(match.group(1))
            current_lines = [match.group(2)]
            continue

        if current_role is None:
            current_role = "user" if not messages else "assistant"
        current_lines.append(raw_line)

    flush()

    if not messages:
        messages = [Message(role="user", content=text)]

    return [Conversation(title=title, messages=messages, source=source)]


def build_path_to_current(mapping: dict[str, Any], current_node: str | None) -> list[str]:
    if not mapping:
        return []

    if current_node and current_node in mapping:
        path: list[str] = []
        seen: set[str] = set()
        node_id = current_node
        while node_id and node_id not in seen and node_id in mapping:
            seen.add(node_id)
            path.append(node_id)
            node_id = mapping[node_id].get("parent")
        path.reverse()
        return path

    nodes_with_time: list[tuple[float, str]] = []
    for node_id, node in mapping.items():
        message = (node or {}).get("message") or {}
        created = message.get("create_time") or 0
        nodes_with_time.append((created, node_id))
    nodes_with_time.sort(key=lambda item: item[0])
    return [node_id for _, node_id in nodes_with_time]


def parse_chatgpt_export(payload: Any, source: str) -> list[Conversation]:
    conversations: list[Conversation] = []
    if not isinstance(payload, list):
        return conversations

    for index, item in enumerate(payload, start=1):
        if not isinstance(item, dict) or "mapping" not in item:
            continue

        mapping = item.get("mapping") or {}
        ordered_ids = build_path_to_current(mapping, item.get("current_node"))
        messages: list[Message] = []

        for node_id in ordered_ids:
            node = mapping.get(node_id) or {}
            message = node.get("message") or {}
            author = message.get("author") or {}
            role = normalize_role(author.get("role") or author.get("name"))
            content = extract_text(message.get("content")).strip()
            if not content:
                continue
            messages.append(
                Message(
                    role=role,
                    content=content,
                    timestamp=message.get("create_time"),
                    speaker=author.get("name") or "",
                )
            )

        if not messages:
            continue

        title = (item.get("title") or f"会话 {index}").strip()
        conversations.append(
            Conversation(
                title=title,
                messages=messages,
                source=source,
                created_at=item.get("create_time") or item.get("update_time"),
            )
        )

    return conversations


def parse_generic_message_objects(payload: Any, source: str, default_title: str) -> list[Conversation]:
    def parse_message_list(items: list[Any], title: str) -> Conversation | None:
        messages: list[Message] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            role = normalize_role(
                item.get("role")
                or ((item.get("author") or {}).get("role") if isinstance(item.get("author"), dict) else "")
                or item.get("speaker")
                or item.get("name")
            )
            content = extract_text(
                item.get("content")
                if "content" in item
                else item.get("text")
                if "text" in item
                else item.get("message")
                if "message" in item
                else item.get("parts")
            ).strip()
            if not content:
                continue
            messages.append(
                Message(
                    role=role,
                    content=content,
                    timestamp=item.get("create_time") or item.get("timestamp"),
                    speaker=item.get("speaker") or item.get("name") or "",
                )
            )
        if not messages:
            return None
        return Conversation(title=title, messages=messages, source=source)

    if isinstance(payload, list):
        conversation = parse_message_list(payload, default_title)
        return [conversation] if conversation else []

    if isinstance(payload, dict):
        for key in ("messages", "conversation", "chat", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                title = payload.get("title") or default_title
                conversation = parse_message_list(value, str(title))
                return [conversation] if conversation else []
        if all(key in payload for key in ("role", "content")):
            conversation = parse_message_list([payload], default_title)
            return [conversation] if conversation else []

    return []


def load_conversations_from_json(path: Path) -> list[Conversation]:
    payload = json.loads(read_text_file(path))
    conversations = parse_chatgpt_export(payload, source=str(path))
    if conversations:
        return conversations
    conversations = parse_generic_message_objects(payload, source=str(path), default_title=path.stem)
    if conversations:
        return conversations
    raise ValueError("暂不支持这个 JSON 结构。可用格式见 README。")


def load_conversations_from_path(path: Path) -> list[Conversation]:
    suffix = path.suffix.lower()
    if suffix == ".json":
        return load_conversations_from_json(path)
    if suffix in {".txt", ".md"}:
        return parse_plain_transcript(read_text_file(path), title=path.stem, source=str(path))
    raise ValueError("仅支持 .json / .txt / .md 文件。")


def render_paragraphs(text: str) -> str:
    paragraphs = [segment.strip() for segment in re.split(r"\n{2,}", text) if segment.strip()]
    rendered: list[str] = []
    for paragraph in paragraphs:
        line_html = "<br>".join(html.escape(line) for line in paragraph.split("\n"))
        rendered.append(f"<p>{line_html}</p>")
    return "\n".join(rendered)


def render_text_blocks(text: str) -> str:
    text = text.replace("\r\n", "\n").strip()
    if not text:
        return "<p class='empty'>[空内容]</p>"

    pattern = re.compile(r"```([\w.+-]*)\n(.*?)```", re.DOTALL)
    parts: list[str] = []
    cursor = 0

    for match in pattern.finditer(text):
        plain = text[cursor:match.start()]
        if plain.strip():
            parts.append(render_paragraphs(plain))

        lang = html.escape(match.group(1).strip() or "code")
        code = html.escape(match.group(2).rstrip())
        parts.append(
            "<div class='code-block'>"
            f"<div class='code-lang'>{lang}</div>"
            f"<pre><code>{code}</code></pre>"
            "</div>"
        )
        cursor = match.end()

    tail = text[cursor:]
    if tail.strip():
        parts.append(render_paragraphs(tail))

    return "\n".join(parts) if parts else "<p class='empty'>[空内容]</p>"


def build_html(conversation: Conversation) -> str:
    created_at = format_timestamp(conversation.created_at)
    message_count = len(conversation.messages)
    header_meta: list[str] = []
    if created_at:
        header_meta.append(f"创建时间: {created_at}")
    if conversation.source:
        header_meta.append(f"来源: {conversation.source}")
    header_meta.append(f"消息数: {message_count}")

    blocks: list[str] = []
    for index, message in enumerate(conversation.messages, start=1):
        role = normalize_role(message.role)
        label = ROLE_LABELS.get(role, role.title())
        timestamp = format_timestamp(message.timestamp)
        speaker = html.escape(message.speaker) if message.speaker else ""
        extra = " · ".join(item for item in (speaker, timestamp) if item)
        blocks.append(
            "<section class='message {role_class}'>"
            "<div class='meta'>"
            f"<span class='badge'>{label}</span>"
            f"<span class='index'>#{index}</span>"
            f"<span class='extra'>{html.escape(extra)}</span>"
            "</div>"
            f"<div class='content'>{render_text_blocks(message.content)}</div>"
            "</section>".format(role_class=ROLE_STYLES.get(role, "assistant"))
        )

    meta_html = "".join(f"<span>{html.escape(item)}</span>" for item in header_meta)
    title_html = html.escape(conversation.title)

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>{title_html}</title>
  <style>
    @page {{
      size: A4;
      margin: 14mm 12mm 15mm 12mm;
    }}
    :root {{
      --ink: #0f172a;
      --muted: #475569;
      --line: #dbe3ef;
      --card: #ffffff;
      --user-bg: #e0f2fe;
      --user-line: #7dd3fc;
      --assistant-bg: #ecfccb;
      --assistant-line: #a3e635;
      --system-bg: #fee2e2;
      --system-line: #fca5a5;
      --tool-bg: #ede9fe;
      --tool-line: #c4b5fd;
      --code-bg: #0f172a;
      --code-ink: #e2e8f0;
    }}
    * {{
      box-sizing: border-box;
    }}
    body {{
      margin: 0;
      color: var(--ink);
      background: linear-gradient(180deg, #f8fafc 0%, #eef6ff 100%);
      font-family: "Microsoft YaHei", "PingFang SC", "Segoe UI", sans-serif;
      font-size: 12pt;
      line-height: 1.65;
    }}
    .header {{
      padding: 0 0 14px 0;
      border-bottom: 2px solid #1e293b;
      margin-bottom: 16px;
    }}
    .header h1 {{
      margin: 0 0 8px;
      font-size: 22pt;
      line-height: 1.25;
    }}
    .meta-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      color: var(--muted);
      font-size: 10pt;
    }}
    .meta-row span {{
      padding: 4px 10px;
      border-radius: 999px;
      background: rgba(255, 255, 255, 0.7);
      border: 1px solid var(--line);
    }}
    .message {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 12px 14px;
      margin-bottom: 12px;
      break-inside: avoid;
      box-shadow: 0 8px 24px rgba(15, 23, 42, 0.05);
    }}
    .message.user {{
      background: linear-gradient(180deg, var(--user-bg) 0%, #ffffff 100%);
      border-color: var(--user-line);
    }}
    .message.assistant {{
      background: linear-gradient(180deg, var(--assistant-bg) 0%, #ffffff 100%);
      border-color: var(--assistant-line);
    }}
    .message.system {{
      background: linear-gradient(180deg, var(--system-bg) 0%, #ffffff 100%);
      border-color: var(--system-line);
    }}
    .message.tool {{
      background: linear-gradient(180deg, var(--tool-bg) 0%, #ffffff 100%);
      border-color: var(--tool-line);
    }}
    .meta {{
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 8px;
      margin-bottom: 10px;
      font-size: 10pt;
      color: var(--muted);
    }}
    .badge {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 48px;
      padding: 3px 10px;
      border-radius: 999px;
      background: rgba(15, 23, 42, 0.08);
      color: #0f172a;
      font-weight: 700;
    }}
    .index {{
      font-weight: 700;
    }}
    .extra {{
      margin-left: auto;
    }}
    .content p {{
      margin: 0 0 10px 0;
      word-break: break-word;
    }}
    .content p:last-child {{
      margin-bottom: 0;
    }}
    .code-block {{
      margin: 10px 0 12px;
      border-radius: 14px;
      overflow: hidden;
      border: 1px solid rgba(15, 23, 42, 0.08);
    }}
    .code-lang {{
      padding: 6px 10px;
      background: #111827;
      color: #cbd5e1;
      font: 10pt "Consolas", "Cascadia Code", monospace;
      text-transform: lowercase;
    }}
    pre {{
      margin: 0;
      padding: 12px;
      background: var(--code-bg);
      color: var(--code-ink);
      font: 10pt/1.5 "Consolas", "Cascadia Code", monospace;
      white-space: pre-wrap;
      word-break: break-word;
    }}
    .empty {{
      color: var(--muted);
      font-style: italic;
    }}
    .footer {{
      margin-top: 16px;
      color: var(--muted);
      font-size: 9pt;
      text-align: right;
    }}
  </style>
</head>
<body>
  <main>
    <header class="header">
      <h1>{title_html}</h1>
      <div class="meta-row">{meta_html}</div>
    </header>
    {''.join(blocks)}
    <div class="footer">由 {APP_NAME} 生成</div>
  </main>
</body>
</html>
"""


def build_markdown(conversation: Conversation) -> str:
    lines = [f"# {conversation.title}", ""]
    if conversation.source:
        lines.append(f"来源: {conversation.source}")
        lines.append("")
    if conversation.created_at:
        lines.append(f"创建时间: {format_timestamp(conversation.created_at)}")
        lines.append("")

    for index, message in enumerate(conversation.messages, start=1):
        label = ROLE_LABELS.get(normalize_role(message.role), "助手")
        lines.append(f"## {index}. {label}")
        if message.timestamp:
            lines.append(f"时间: {format_timestamp(message.timestamp)}")
        lines.append("")
        lines.append(message.content.strip())
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def export_conversation_to_html(conversation: Conversation, output_html: Path) -> Path:
    output_html.parent.mkdir(parents=True, exist_ok=True)
    output_html.write_text(build_html(conversation), encoding="utf-8")
    return output_html


def split_content_blocks(text: str) -> list[tuple[str, str]]:
    text = text.replace("\r\n", "\n").strip()
    if not text:
        return []
    pattern = re.compile(r"```([\w.+-]*)\n(.*?)```", re.DOTALL)
    blocks: list[tuple[str, str]] = []
    cursor = 0

    for match in pattern.finditer(text):
        plain = text[cursor:match.start()].strip()
        if plain:
            blocks.append(("text", plain))
        lang = match.group(1).strip()
        code = match.group(2).rstrip()
        header = f"[{lang}]\n" if lang else ""
        blocks.append(("code", header + code))
        cursor = match.end()

    tail = text[cursor:].strip()
    if tail:
        blocks.append(("text", tail))
    return blocks


def build_pdf_styles() -> dict[str, ParagraphStyle]:
    register_pdf_fonts()
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "ChatTitle",
            parent=base["Title"],
            fontName=PDF_FONT_BOLD_NAME,
            fontSize=21,
            leading=28,
            textColor=colors.HexColor("#0f172a"),
            spaceAfter=8,
        ),
        "meta": ParagraphStyle(
            "ChatMeta",
            parent=base["Normal"],
            fontName=PDF_FONT_NAME,
            fontSize=9.5,
            leading=14,
            textColor=colors.HexColor("#475569"),
            spaceAfter=6,
        ),
        "role": ParagraphStyle(
            "ChatRole",
            parent=base["Normal"],
            fontName=PDF_FONT_BOLD_NAME,
            fontSize=11.5,
            leading=16,
            textColor=colors.HexColor("#0f172a"),
            spaceAfter=5,
        ),
        "body": ParagraphStyle(
            "ChatBody",
            parent=base["Normal"],
            fontName=PDF_FONT_NAME,
            fontSize=10.5,
            leading=17,
            textColor=colors.HexColor("#111827"),
            spaceAfter=4,
        ),
        "code": ParagraphStyle(
            "ChatCode",
            parent=base["Code"],
            fontName="Courier",
            fontSize=9,
            leading=12,
            leftIndent=8,
            rightIndent=8,
            borderPadding=8,
            backColor=colors.HexColor("#0f172a"),
            textColor=colors.HexColor("#e2e8f0"),
            borderRadius=4,
            spaceBefore=2,
            spaceAfter=6,
        ),
        "footer": ParagraphStyle(
            "ChatFooter",
            parent=base["Normal"],
            fontName=PDF_FONT_NAME,
            fontSize=8.5,
            leading=12,
            textColor=colors.HexColor("#64748b"),
            alignment=TA_RIGHT,
        ),
    }


def escape_paragraph_text(text: str) -> str:
    return "<br/>".join(html.escape(line) for line in text.split("\n"))


def build_story(conversation: Conversation) -> tuple[list[Any], dict[str, ParagraphStyle]]:
    styles = build_pdf_styles()
    story: list[Any] = []

    story.append(Paragraph(html.escape(conversation.title), styles["title"]))
    meta_bits: list[str] = []
    if conversation.created_at:
        meta_bits.append(f"创建时间: {format_timestamp(conversation.created_at)}")
    if conversation.source:
        meta_bits.append(f"来源: {conversation.source}")
    meta_bits.append(f"消息数: {len(conversation.messages)}")
    story.append(Paragraph(html.escape(" | ".join(meta_bits)), styles["meta"]))
    story.append(Spacer(1, 6))

    role_colors = {
        "user": "#0ea5e9",
        "assistant": "#65a30d",
        "system": "#dc2626",
        "tool": "#7c3aed",
    }

    for index, message in enumerate(conversation.messages, start=1):
        role = normalize_role(message.role)
        label = ROLE_LABELS.get(role, "助手")
        timestamp = format_timestamp(message.timestamp)
        speaker = message.speaker.strip()
        extra = " · ".join(bit for bit in [f"#{index}", speaker, timestamp] if bit)
        role_color = role_colors.get(role, "#334155")
        heading = f"<font color='{role_color}'>{html.escape(label)}</font> <font color='#64748b'>{html.escape(extra)}</font>"
        story.append(Paragraph(heading, styles["role"]))

        blocks = split_content_blocks(message.content)
        if not blocks:
            story.append(Paragraph("[空内容]", styles["body"]))
        for kind, block in blocks:
            if kind == "code":
                story.append(Preformatted(block, styles["code"]))
                continue
            paragraphs = [part.strip() for part in re.split(r"\n{2,}", block) if part.strip()]
            for part in paragraphs:
                story.append(Paragraph(escape_paragraph_text(part), styles["body"]))
        story.append(Spacer(1, 3))
        story.append(HRFlowable(width="100%", thickness=0.6, color=colors.HexColor("#dbe3ef")))
        story.append(Spacer(1, 10))

    return story, styles


def draw_footer(canvas: Any, doc: Any) -> None:
    page_text = f"{APP_NAME}  |  第 {canvas.getPageNumber()} 页"
    canvas.saveState()
    canvas.setFont(PDF_FONT_NAME, 8.5)
    canvas.setFillColor(colors.HexColor("#64748b"))
    canvas.drawRightString(doc.pagesize[0] - 15 * mm, 10 * mm, page_text)
    canvas.restoreState()


def export_conversation_to_pdf(
    conversation: Conversation,
    output_pdf: Path,
    export_markdown: bool = False,
) -> tuple[Path, Path | None]:
    if REPORTLAB_READY:
        return export_conversation_to_pdf_with_reportlab(
            conversation=conversation,
            output_pdf=output_pdf,
            export_markdown=export_markdown,
        )
    return export_conversation_to_pdf_with_browser(
        conversation=conversation,
        output_pdf=output_pdf,
        export_markdown=export_markdown,
    )


def export_conversation_to_pdf_with_reportlab(
    conversation: Conversation,
    output_pdf: Path,
    export_markdown: bool = False,
) -> tuple[Path, Path | None]:
    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    story, _styles = build_story(conversation)
    doc = SimpleDocTemplate(
        str(output_pdf),
        pagesize=A4,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=15 * mm,
        bottomMargin=16 * mm,
        title=conversation.title,
        author=APP_NAME,
    )
    doc.build(story, onFirstPage=draw_footer, onLaterPages=draw_footer)

    markdown_path: Path | None = None
    if export_markdown:
        markdown_path = output_pdf.with_suffix(".md")
        markdown_path.write_text(build_markdown(conversation), encoding="utf-8")
    return output_pdf, markdown_path


def export_conversation_to_pdf_with_browser(
    conversation: Conversation,
    output_pdf: Path,
    export_markdown: bool = False,
) -> tuple[Path, Path | None]:
    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    browser = find_browser()
    workspace_tmp = (Path.cwd() / TMP_DIR).resolve()
    workspace_tmp.mkdir(parents=True, exist_ok=True)
    token = f"{safe_filename(conversation.title)}_{int(time.time() * 1000)}"
    html_path = workspace_tmp / f"{token}.html"
    try:
        html_path.write_text(build_html(conversation), encoding="utf-8")

        command = [
            str(browser),
            "--headless",
            "--disable-gpu",
            "--allow-file-access-from-files",
            "--run-all-compositor-stages-before-draw",
            "--virtual-time-budget=2500",
            "--no-pdf-header-footer",
            f"--print-to-pdf={output_pdf.resolve()}",
            html_path.resolve().as_uri(),
        ]

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=90,
            check=False,
        )
        if result.returncode != 0 or not output_pdf.exists():
            fallback_html = output_pdf.with_suffix(".html")
            export_conversation_to_html(conversation, fallback_html)
            if export_markdown:
                output_pdf.with_suffix(".md").write_text(build_markdown(conversation), encoding="utf-8")
            details = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(
                (details + "\n\n" if details else "")
                + f"浏览器导出 PDF 失败。已保留 HTML 预览文件: {fallback_html}"
            )
    finally:
        time.sleep(0.2)
        if html_path.exists():
            try:
                html_path.unlink()
            except OSError:
                pass

    markdown_path: Path | None = None
    if export_markdown:
        markdown_path = output_pdf.with_suffix(".md")
        markdown_path.write_text(build_markdown(conversation), encoding="utf-8")

    return output_pdf, markdown_path


def export_many_conversations(
    conversations: list[Conversation],
    output_dir: Path,
    export_markdown: bool = False,
) -> list[tuple[Path, Path | None]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    exported: list[tuple[Path, Path | None]] = []
    for index, conversation in enumerate(conversations, start=1):
        base = safe_filename(f"{index:02d}-{conversation.title}")
        exported.append(
            export_conversation_to_pdf(
                conversation=conversation,
                output_pdf=output_dir / f"{base}.pdf",
                export_markdown=export_markdown,
            )
        )
    return exported


def conversation_preview(conversation: Conversation) -> str:
    lines = [f"标题: {conversation.title}", f"消息数: {len(conversation.messages)}", ""]
    for message in conversation.messages:
        label = ROLE_LABELS.get(normalize_role(message.role), "助手")
        lines.append(f"[{label}]")
        lines.append(message.content.strip())
        lines.append("")
    return "\n".join(lines).strip()


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(APP_NAME)
        self.root.geometry("1180x760")
        self.root.minsize(960, 640)

        self.conversations: list[Conversation] = []
        self.current_source = ""
        self.export_markdown_var = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar(value="准备就绪。支持导入 .json / .txt / .md")
        self.count_var = tk.StringVar(value="当前没有会话")

        self.setup_style()
        self.build_ui()

    def setup_style(self) -> None:
        style = ttk.Style()
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("TFrame", background="#f6f8fc")
        style.configure("Header.TLabel", background="#f6f8fc", foreground="#0f172a", font=("Microsoft YaHei UI", 16, "bold"))
        style.configure("Sub.TLabel", background="#f6f8fc", foreground="#475569", font=("Microsoft YaHei UI", 10))
        style.configure("Action.TButton", font=("Microsoft YaHei UI", 10, "bold"))
        style.configure("TLabel", background="#f6f8fc", foreground="#0f172a", font=("Microsoft YaHei UI", 10))
        style.configure("TLabelframe", background="#f6f8fc", foreground="#0f172a")
        style.configure("TLabelframe.Label", background="#f6f8fc", foreground="#0f172a", font=("Microsoft YaHei UI", 10, "bold"))

    def build_ui(self) -> None:
        root_frame = ttk.Frame(self.root, padding=16)
        root_frame.pack(fill="both", expand=True)

        header = ttk.Frame(root_frame)
        header.pack(fill="x")

        ttk.Label(header, text=APP_NAME, style="Header.TLabel").pack(anchor="w")
        ttk.Label(
            header,
            text="导入 ChatGPT JSON、通用 role/content JSON，或带角色标记的 txt/md 文本，然后导出成 PDF。",
            style="Sub.TLabel",
        ).pack(anchor="w", pady=(4, 0))

        action_bar = ttk.Frame(root_frame)
        action_bar.pack(fill="x", pady=(16, 10))

        ttk.Button(action_bar, text="导入文件", style="Action.TButton", command=self.load_file).pack(side="left")
        ttk.Button(action_bar, text="读取剪贴板", command=self.load_clipboard).pack(side="left", padx=(8, 0))
        ttk.Button(action_bar, text="清空", command=self.clear_all).pack(side="left", padx=(8, 0))
        ttk.Button(action_bar, text="打开输出目录", command=self.open_output_dir).pack(side="left", padx=(8, 0))

        ttk.Checkbutton(
            action_bar,
            text="同时导出 Markdown（更适合重新喂给模型）",
            variable=self.export_markdown_var,
        ).pack(side="right")

        main = ttk.Panedwindow(root_frame, orient="horizontal")
        main.pack(fill="both", expand=True)

        left_box = ttk.Labelframe(main, text="会话列表", padding=10)
        right_box = ttk.Labelframe(main, text="预览", padding=10)
        main.add(left_box, weight=1)
        main.add(right_box, weight=3)

        ttk.Label(left_box, textvariable=self.count_var).pack(anchor="w")

        list_frame = ttk.Frame(left_box)
        list_frame.pack(fill="both", expand=True, pady=(8, 0))

        self.conversation_list = tk.Listbox(
            list_frame,
            font=("Microsoft YaHei UI", 10),
            bd=0,
            highlightthickness=1,
            highlightbackground="#dbe3ef",
            activestyle="none",
            selectbackground="#dbeafe",
            selectforeground="#0f172a",
        )
        list_scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.conversation_list.yview)
        self.conversation_list.configure(yscrollcommand=list_scroll.set)
        self.conversation_list.pack(side="left", fill="both", expand=True)
        list_scroll.pack(side="right", fill="y")
        self.conversation_list.bind("<<ListboxSelect>>", self.on_select)

        self.preview = tk.Text(
            right_box,
            wrap="word",
            font=("Microsoft YaHei UI", 10),
            bd=0,
            padx=10,
            pady=10,
            highlightthickness=1,
            highlightbackground="#dbe3ef",
        )
        preview_scroll = ttk.Scrollbar(right_box, orient="vertical", command=self.preview.yview)
        self.preview.configure(yscrollcommand=preview_scroll.set, state="disabled")
        self.preview.pack(side="left", fill="both", expand=True)
        preview_scroll.pack(side="right", fill="y")

        footer = ttk.Frame(root_frame)
        footer.pack(fill="x", pady=(12, 0))

        ttk.Label(footer, textvariable=self.status_var).pack(side="left")
        ttk.Button(footer, text="导出当前会话 PDF", style="Action.TButton", command=self.export_current).pack(side="right")
        ttk.Button(footer, text="批量导出全部", command=self.export_all).pack(side="right", padx=(0, 8))

    def set_status(self, text: str) -> None:
        self.status_var.set(text)
        self.root.update_idletasks()

    def load_file(self) -> None:
        path_str = filedialog.askopenfilename(
            title="选择聊天记录文件",
            filetypes=[
                ("聊天记录", "*.json *.txt *.md"),
                ("JSON", "*.json"),
                ("Text / Markdown", "*.txt *.md"),
                ("全部文件", "*.*"),
            ],
        )
        if not path_str:
            return

        path = Path(path_str)
        try:
            conversations = load_conversations_from_path(path)
        except Exception as exc:
            messagebox.showerror("导入失败", str(exc))
            self.set_status("导入失败。")
            return

        self.current_source = str(path)
        self.set_conversations(conversations)
        self.set_status(f"已导入 {len(conversations)} 个会话。来源: {path.name}")

    def load_clipboard(self) -> None:
        try:
            text = self.root.clipboard_get()
        except tk.TclError:
            messagebox.showwarning("剪贴板为空", "当前剪贴板里没有可读取的文本。")
            return

        conversations = parse_plain_transcript(text, title="剪贴板内容", source="clipboard")
        if not conversations:
            messagebox.showwarning("没有内容", "剪贴板里没有可识别的聊天文本。")
            return
        self.current_source = "clipboard"
        self.set_conversations(conversations)
        self.set_status("已从剪贴板导入 1 个会话。")

    def clear_all(self) -> None:
        self.conversations = []
        self.current_source = ""
        self.conversation_list.delete(0, tk.END)
        self.count_var.set("当前没有会话")
        self.show_preview("")
        self.set_status("已清空。")

    def open_output_dir(self) -> None:
        output_dir = (Path.cwd() / OUTPUT_DIR).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        os.startfile(str(output_dir))

    def set_conversations(self, conversations: list[Conversation]) -> None:
        self.conversations = conversations
        self.conversation_list.delete(0, tk.END)
        for conversation in conversations:
            self.conversation_list.insert(tk.END, conversation.title)

        self.count_var.set(f"共 {len(conversations)} 个会话")
        if conversations:
            self.conversation_list.selection_set(0)
            self.on_select()
        else:
            self.show_preview("")

    def selected_index(self) -> int | None:
        selection = self.conversation_list.curselection()
        if not selection:
            return None
        return int(selection[0])

    def on_select(self, event: Any | None = None) -> None:
        index = self.selected_index()
        if index is None or index >= len(self.conversations):
            self.show_preview("")
            return
        self.show_preview(conversation_preview(self.conversations[index]))

    def show_preview(self, text: str) -> None:
        self.preview.configure(state="normal")
        self.preview.delete("1.0", tk.END)
        self.preview.insert("1.0", text)
        self.preview.configure(state="disabled")

    def export_current(self) -> None:
        index = self.selected_index()
        if index is None:
            messagebox.showwarning("没有会话", "请先导入聊天记录并选择一个会话。")
            return

        conversation = self.conversations[index]
        default_name = f"{safe_filename(conversation.title)}.pdf"
        path_str = filedialog.asksaveasfilename(
            title="导出当前会话 PDF",
            defaultextension=".pdf",
            initialdir=str((Path.cwd() / OUTPUT_DIR).resolve()),
            initialfile=default_name,
            filetypes=[("PDF 文件", "*.pdf")],
        )
        if not path_str:
            return

        output_pdf = Path(path_str)
        self.set_status("正在导出当前会话，请稍候...")
        try:
            pdf_path, md_path = export_conversation_to_pdf(
                conversation,
                output_pdf,
                export_markdown=self.export_markdown_var.get(),
            )
        except Exception as exc:
            messagebox.showerror("导出失败", str(exc))
            self.set_status("导出失败。")
            return

        message = f"PDF 已导出: {pdf_path}"
        if md_path:
            message += f"\nMarkdown 已导出: {md_path}"
        messagebox.showinfo("导出成功", message)
        self.set_status("当前会话导出完成。")

    def export_all(self) -> None:
        if not self.conversations:
            messagebox.showwarning("没有会话", "请先导入聊天记录。")
            return

        folder = filedialog.askdirectory(
            title="选择批量导出的文件夹",
            initialdir=str((Path.cwd() / OUTPUT_DIR).resolve()),
            mustexist=False,
        )
        if not folder:
            return

        output_dir = Path(folder)
        self.set_status(f"正在批量导出 {len(self.conversations)} 个会话...")
        try:
            exported = export_many_conversations(
                self.conversations,
                output_dir=output_dir,
                export_markdown=self.export_markdown_var.get(),
            )
        except Exception as exc:
            messagebox.showerror("批量导出失败", str(exc))
            self.set_status("批量导出失败。")
            return

        messagebox.showinfo("批量导出成功", f"已导出 {len(exported)} 个 PDF 到:\n{output_dir}")
        self.set_status(f"批量导出完成，已输出到 {output_dir}")


def run_cli(args: argparse.Namespace) -> int:
    input_path = Path(args.input)
    conversations = load_conversations_from_path(input_path)
    export_markdown = bool(args.markdown)

    if args.all:
        output_dir = Path(args.output or OUTPUT_DIR / safe_filename(input_path.stem))
        exported = export_many_conversations(
            conversations,
            output_dir=output_dir,
            export_markdown=export_markdown,
        )
        print(f"已导出 {len(exported)} 个会话到: {output_dir.resolve()}")
        return 0

    conversation = conversations[0]
    if args.title:
        conversation.title = args.title

    output_path = Path(args.output or OUTPUT_DIR / f"{safe_filename(conversation.title)}.pdf")
    pdf_path, markdown_path = export_conversation_to_pdf(
        conversation,
        output_pdf=output_path,
        export_markdown=export_markdown,
    )
    print(f"PDF: {pdf_path.resolve()}")
    if markdown_path:
        print(f"Markdown: {markdown_path.resolve()}")
    if len(conversations) > 1:
        print("提示: 该输入中包含多个会话，当前 CLI 默认只导出了第一个。如需全部导出，请加 --all。")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--input", help="输入文件路径，支持 .json / .txt / .md")
    parser.add_argument("--output", help="输出 PDF 路径；批量模式下表示输出目录")
    parser.add_argument("--title", help="覆盖导出的标题")
    parser.add_argument("--all", action="store_true", help="批量导出全部会话")
    parser.add_argument("--markdown", action="store_true", help="同时导出 Markdown")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.input:
        try:
            return run_cli(args)
        except Exception as exc:
            print(f"导出失败: {exc}", file=sys.stderr)
            return 1

    root = tk.Tk()
    App(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
