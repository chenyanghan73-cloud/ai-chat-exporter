const ROLE_LABELS = {
  user: "用户",
  assistant: "助手",
  system: "系统",
  tool: "工具"
};

const SITE_LABELS = {
  chatgpt: "ChatGPT",
  claude: "Claude",
  gemini: "Gemini",
  generic: "通用页面"
};

export function normalizeRole(role) {
  const value = String(role || "").trim().toLowerCase();
  if (
    ["user", "human", "用户", "我"].includes(value)
    || value.includes("user")
    || value.includes("human")
  ) {
    return "user";
  }
  if (
    ["assistant", "助手", "chatgpt", "claude", "gemini", "ai", "bot", "model"].includes(value)
    || value.includes("assistant")
    || value.includes("model")
    || value.includes("bot")
  ) {
    return "assistant";
  }
  if (["system", "系统"].includes(value)) {
    return "system";
  }
  if (["tool", "工具", "function"].includes(value)) {
    return "tool";
  }
  return "assistant";
}

export function siteLabel(site) {
  return SITE_LABELS[site] || SITE_LABELS.generic;
}

export function roleLabel(role) {
  return ROLE_LABELS[normalizeRole(role)] || "助手";
}

export function formatTimestamp(value) {
  if (!value) {
    return "";
  }
  const date = typeof value === "number" ? new Date(value) : new Date(String(value));
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit"
  }).format(date);
}

export function safeFilename(text, fallback = "chat-export") {
  const cleaned = String(text || "")
    .replace(/[\\/:*?"<>|]+/g, "_")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/^\.+|\.+$/g, "");
  return (cleaned || fallback).slice(0, 80);
}

export function escapeHtml(text) {
  return String(text || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

export function splitContentBlocks(text) {
  const source = String(text || "").replace(/\r\n/g, "\n").trim();
  if (!source) {
    return [];
  }

  const pattern = /```([\w.+-]*)\n([\s\S]*?)```/g;
  const blocks = [];
  let cursor = 0;
  let match = pattern.exec(source);

  while (match) {
    const plain = source.slice(cursor, match.index).trim();
    if (plain) {
      blocks.push({ type: "text", value: plain });
    }

    const lang = match[1].trim();
    const code = match[2].replace(/\n$/, "");
    blocks.push({ type: "code", value: code, lang });

    cursor = match.index + match[0].length;
    match = pattern.exec(source);
  }

  const tail = source.slice(cursor).trim();
  if (tail) {
    blocks.push({ type: "text", value: tail });
  }

  return blocks;
}

function renderParagraphs(text) {
  return String(text || "")
    .split(/\n{2,}/)
    .map((part) => part.trim())
    .filter(Boolean)
    .map((part) => `<p>${escapeHtml(part).replace(/\n/g, "<br>")}</p>`)
    .join("");
}

export function renderMessageHtml(text) {
  const blocks = splitContentBlocks(text);
  if (!blocks.length) {
    return "<p class=\"empty\">[空内容]</p>";
  }

  return blocks
    .map((block) => {
      if (block.type === "code") {
        const lang = block.lang ? `<div class="code-lang">${escapeHtml(block.lang)}</div>` : "";
        return `${lang}<pre><code>${escapeHtml(block.value)}</code></pre>`;
      }
      return renderParagraphs(block.value);
    })
    .join("");
}

export function buildMarkdown(conversation) {
  const lines = [`# ${conversation.title || "未命名会话"}`, ""];

  if (conversation.site) {
    lines.push(`来源站点: ${siteLabel(conversation.site)}`);
    lines.push("");
  }

  if (conversation.sourceUrl) {
    lines.push(`来源链接: ${conversation.sourceUrl}`);
    lines.push("");
  }

  if (conversation.capturedAt) {
    lines.push(`抓取时间: ${formatTimestamp(conversation.capturedAt)}`);
    lines.push("");
  }

  for (const [index, message] of (conversation.messages || []).entries()) {
    lines.push(`## ${index + 1}. ${roleLabel(message.role)}`);
    if (message.timestamp) {
      lines.push(`时间: ${formatTimestamp(message.timestamp)}`);
    }
    lines.push("");
    lines.push(String(message.content || "").trim());
    lines.push("");
  }

  return `${lines.join("\n").trim()}\n`;
}

export function buildPlainText(conversation) {
  const lines = [];
  for (const message of conversation.messages || []) {
    lines.push(`${roleLabel(message.role)}: ${String(message.content || "").trim()}`);
    lines.push("");
  }
  return lines.join("\n").trim();
}
