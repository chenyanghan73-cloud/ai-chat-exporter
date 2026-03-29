import {
  buildMarkdown,
  escapeHtml,
  formatTimestamp,
  normalizeRole,
  renderMessageHtml,
  roleLabel,
  safeFilename,
  siteLabel
} from "./shared/export-utils.js";

const page = document.querySelector("#page");
const emptyState = document.querySelector("#empty-state");
const toolbarTitle = document.querySelector("#toolbar-title");
const printButton = document.querySelector("#print-button");
const markdownButton = document.querySelector("#markdown-button");
const jsonButton = document.querySelector("#json-button");

printButton.addEventListener("click", () => window.print());
markdownButton.addEventListener("click", () => void downloadMarkdown());
jsonButton.addEventListener("click", () => void downloadJson());

const params = new URLSearchParams(window.location.search);
const storageKey = params.get("id");
const autoPrint = params.get("autoprint") === "1";

let currentConversation = null;

void init();

async function init() {
  if (!storageKey) {
    renderError("没有找到会话数据。请回到扩展弹窗重新抓取。");
    return;
  }

  const stored = await chrome.storage.local.get(storageKey);
  currentConversation = stored[storageKey] || null;
  if (!currentConversation) {
    renderError("会话数据已经失效。请回到扩展弹窗重新抓取。");
    return;
  }

  renderConversation(currentConversation);

  if (autoPrint) {
    setTimeout(() => window.print(), 450);
  }
}

function renderConversation(conversation) {
  toolbarTitle.textContent = conversation.title || "未命名会话";
  emptyState.remove();

  const metaBits = [
    `站点: ${siteLabel(conversation.site)}`,
    `消息数: ${(conversation.messages || []).length}`
  ];

  if (conversation.capturedAt) {
    metaBits.push(`抓取时间: ${formatTimestamp(conversation.capturedAt)}`);
  }

  if (conversation.sourceUrl) {
    metaBits.push(`来源: ${conversation.sourceUrl}`);
  }

  const paper = document.createElement("article");
  paper.className = "paper";
  paper.innerHTML = `
    <header class="header">
      <h2>${escapeHtml(conversation.title || "未命名会话")}</h2>
      <div class="meta-row">
        ${metaBits.map((bit) => `<span class="meta-pill">${escapeHtml(bit)}</span>`).join("")}
      </div>
    </header>
    <section class="messages">
      ${(conversation.messages || []).map((message, index) => renderMessage(message, index)).join("")}
    </section>
  `;
  page.append(paper);
}

function renderMessage(message, index) {
  const role = normalizeRole(message.role);
  const extras = [];
  if (message.speaker) {
    extras.push(message.speaker);
  }
  if (message.timestamp) {
    extras.push(formatTimestamp(message.timestamp));
  }

  return `
    <section class="message ${role}">
      <div class="message-meta">
        <span class="role-badge">${escapeHtml(roleLabel(role))}</span>
        <span class="message-index">#${index + 1}</span>
        <span class="message-extra">${escapeHtml(extras.join(" · "))}</span>
      </div>
      <div class="message-body">${renderMessageHtml(message.content || "")}</div>
    </section>
  `;
}

function renderError(message) {
  toolbarTitle.textContent = "加载失败";
  emptyState.textContent = message;
}

async function downloadMarkdown() {
  if (!currentConversation) {
    return;
  }
  const markdown = buildMarkdown(currentConversation);
  await downloadText({
    filename: `${safeFilename(currentConversation.title, "chat-export")}.md`,
    content: markdown,
    mimeType: "text/markdown;charset=utf-8"
  });
}

async function downloadJson() {
  if (!currentConversation) {
    return;
  }
  const json = JSON.stringify(currentConversation, null, 2);
  await downloadText({
    filename: `${safeFilename(currentConversation.title, "chat-export")}.json`,
    content: json,
    mimeType: "application/json;charset=utf-8"
  });
}

async function downloadText({ filename, content, mimeType }) {
  const blob = new Blob([content], { type: mimeType });
  const objectUrl = URL.createObjectURL(blob);
  try {
    await chrome.downloads.download({
      url: objectUrl,
      filename,
      saveAs: true
    });
  } finally {
    setTimeout(() => URL.revokeObjectURL(objectUrl), 60000);
  }
}
