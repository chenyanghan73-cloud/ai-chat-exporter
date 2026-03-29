import { buildMarkdown, buildPlainText, safeFilename, siteLabel } from "./shared/export-utils.js";

const siteBadge = document.querySelector("#site-badge");
const pageHint = document.querySelector("#page-hint");
const conversationTitle = document.querySelector("#conversation-title");
const conversationMeta = document.querySelector("#conversation-meta");
const resultBox = document.querySelector("#result-box");
const actionButtons = Array.from(document.querySelectorAll("button"));

const buttonActions = {
  "#print-button": "print",
  "#markdown-button": "markdown",
  "#json-button": "json",
  "#copy-button": "copy"
};

for (const [selector, action] of Object.entries(buttonActions)) {
  document.querySelector(selector).addEventListener("click", () => {
    void runAction(action);
  });
}

void inspectCurrentTab();

async function inspectCurrentTab() {
  try {
    const tab = await getActiveTab();
    const tabUrl = tab && tab.url ? tab.url : "";
    const site = inferSiteFromUrl(tabUrl);
    siteBadge.textContent = siteLabel(site);
    pageHint.textContent = tabUrl ? new URL(tabUrl).hostname : "请切到聊天页面后再使用";
    if (site === "generic") {
      conversationMeta.textContent = "当前页面不是已知站点，扩展会尝试通用抓取。";
    }
  } catch (error) {
    siteBadge.textContent = "未检测到标签页";
    pageHint.textContent = "请切到聊天页面后再使用";
  }
}

async function runAction(action) {
  setBusy(true, "正在抓取当前会话...");
  try {
    const tab = await getActiveTab();
    if (!tab || !tab.id) {
      throw new Error("没有可用的当前标签页。");
    }

    const conversation = await captureConversation(tab.id);
    updateConversationCard(conversation);

    if (action === "print") {
      const key = await storeConversation(conversation);
      const previewUrl = new URL(chrome.runtime.getURL("preview.html"));
      previewUrl.searchParams.set("id", key);
      previewUrl.searchParams.set("autoprint", "1");
      await chrome.tabs.create({ url: previewUrl.toString() });
      setResult("已打开打印预览页，浏览器会自动唤起打印。最后一步请选择“另存为 PDF”。");
      return;
    }

    if (action === "markdown") {
      const markdown = buildMarkdown(conversation);
      await downloadText({
        filename: `${safeFilename(conversation.title, "chat-export")}.md`,
        content: markdown,
        mimeType: "text/markdown;charset=utf-8"
      });
      setResult("Markdown 已准备下载。");
      return;
    }

    if (action === "json") {
      const json = JSON.stringify(conversation, null, 2);
      await downloadText({
        filename: `${safeFilename(conversation.title, "chat-export")}.json`,
        content: json,
        mimeType: "application/json;charset=utf-8"
      });
      setResult("JSON 已准备下载。");
      return;
    }

    if (action === "copy") {
      await navigator.clipboard.writeText(buildPlainText(conversation));
      setResult("纯文本已复制到剪贴板。");
      return;
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    setResult(message, true);
  } finally {
    setBusy(false);
  }
}

async function getActiveTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab;
}

function inferSiteFromUrl(url) {
  if (!url) {
    return "generic";
  }
  try {
    const hostname = new URL(url).hostname.toLowerCase();
    if (hostname.includes("chatgpt.com") || hostname.includes("chat.openai.com")) {
      return "chatgpt";
    }
    if (hostname.includes("claude.ai")) {
      return "claude";
    }
    if (hostname.includes("gemini.google.com")) {
      return "gemini";
    }
    return "generic";
  } catch (error) {
    return "generic";
  }
}

async function captureConversation(tabId) {
  const [{ result }] = await chrome.scripting.executeScript({
    target: { tabId },
    func: extractConversationFromPage
  });

  if (!result || !result.ok) {
    throw new Error((result && result.error) || "未能识别当前会话。");
  }
  return result.conversation;
}

async function storeConversation(conversation) {
  const key = `conversation_export_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
  await chrome.storage.local.set({
    [key]: conversation,
    latestConversationExportKey: key
  });
  return key;
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

function updateConversationCard(conversation) {
  conversationTitle.textContent = conversation.title || "未命名会话";
  conversationMeta.textContent = `${siteLabel(conversation.site)} · ${conversation.messages.length} 条消息`;
  siteBadge.textContent = siteLabel(conversation.site);
  pageHint.textContent = conversation.sourceUrl || "当前页面";
}

function setBusy(isBusy, message = "") {
  for (const button of actionButtons) {
    button.disabled = isBusy;
  }
  if (message) {
    setResult(message);
  }
}

function setResult(message, isError = false) {
  resultBox.textContent = message;
  resultBox.classList.toggle("error", isError);
}

function extractConversationFromPage() {
  function inferSite(hostname) {
    const host = String(hostname || "").toLowerCase();
    if (host.includes("chatgpt.com") || host.includes("chat.openai.com")) {
      return "chatgpt";
    }
    if (host.includes("claude.ai")) {
      return "claude";
    }
    if (host.includes("gemini.google.com")) {
      return "gemini";
    }
    return "generic";
  }

  function normalizeRole(role) {
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

  function cleanTitle(rawTitle) {
    const title = String(rawTitle || "")
      .replace(/\s*[-|·]\s*ChatGPT.*$/i, "")
      .replace(/\s*[-|·]\s*Claude.*$/i, "")
      .replace(/\s*[-|·]\s*Gemini.*$/i, "")
      .trim();
    return title || "未命名会话";
  }

  function detectCodeLanguage(preElement) {
    const attrs = [
      preElement.getAttribute("data-language"),
      (preElement.dataset && preElement.dataset.language) || "",
      preElement.className || ""
    ];
    const joined = attrs.filter(Boolean).join(" ");
    const match = joined.match(/language-([\w.+-]+)/i);
    return match ? match[1].toLowerCase() : "";
  }

  function stripClone(node) {
    const clone = node.cloneNode(true);
    clone.querySelectorAll([
      "button",
      "textarea",
      "input",
      "select",
      "script",
      "style",
      "svg",
      "nav",
      "aside",
      "[aria-hidden='true']",
      "[hidden]",
      "[role='button']"
    ].join(",")).forEach((element) => element.remove());

    clone.querySelectorAll("img, video, canvas").forEach((element) => {
      element.replaceWith(document.createTextNode("\n[媒体]\n"));
    });

    clone.querySelectorAll("a[href]").forEach((link) => {
      const text = (link.innerText || link.textContent || "").trim();
      const href = link.getAttribute("href") || "";
      if (!href || href.startsWith("#")) {
        return;
      }
      if (text && text !== href) {
        link.replaceWith(document.createTextNode(`${text} (${href})`));
        return;
      }
      link.replaceWith(document.createTextNode(href));
    });

    clone.querySelectorAll("pre").forEach((preElement) => {
      const codeText = (preElement.innerText || preElement.textContent || "").trim();
      const lang = detectCodeLanguage(preElement);
      const fenced = `\n\`\`\`${lang}\n${codeText}\n\`\`\`\n`;
      preElement.replaceWith(document.createTextNode(fenced));
    });

    clone.querySelectorAll("br").forEach((br) => {
      br.replaceWith(document.createTextNode("\n"));
    });

    return clone;
  }

  function extractNodeContent(node) {
    const clone = stripClone(node);
    return String(clone.innerText || clone.textContent || "")
      .replace(/\u00a0/g, " ")
      .replace(/\n{3,}/g, "\n\n")
      .replace(/[ \t]+\n/g, "\n")
      .trim();
  }

  function sortInDomOrder(items) {
    return items.sort((left, right) => {
      if (left.node === right.node) {
        return 0;
      }
      const position = left.node.compareDocumentPosition(right.node);
      if (position & Node.DOCUMENT_POSITION_FOLLOWING) {
        return -1;
      }
      if (position & Node.DOCUMENT_POSITION_PRECEDING) {
        return 1;
      }
      return 0;
    });
  }

  function uniqueByNodeAndText(items) {
    const seenNodes = new WeakSet();
    const seenText = new Set();
    const unique = [];

    for (const item of items) {
      if (!item.node || seenNodes.has(item.node)) {
        continue;
      }
      const content = extractNodeContent(item.node);
      if (!content) {
        continue;
      }
      const fingerprint = `${item.role}::${content}`;
      if (seenText.has(fingerprint)) {
        continue;
      }
      seenNodes.add(item.node);
      seenText.add(fingerprint);
      unique.push({
        role: normalizeRole(item.role),
        content,
        timestamp: "",
        speaker: ""
      });
    }

    return unique;
  }

  function extractChatGptMessages() {
    return sortInDomOrder(
      Array.from(document.querySelectorAll("[data-message-author-role]")).map((node) => ({
        node,
        role: node.getAttribute("data-message-author-role") || "assistant"
      }))
    );
  }

  function extractClaudeMessages() {
    const selectors = [
      { selector: "[data-testid='user-message']", role: "user" },
      { selector: "[data-testid='assistant-message']", role: "assistant" },
      { selector: "[data-testid*='user-message']", role: "user" },
      { selector: "[data-testid*='assistant-message']", role: "assistant" },
      { selector: "[data-testid='conversation-turn-user']", role: "user" },
      { selector: "[data-testid='conversation-turn-assistant']", role: "assistant" }
    ];

    const items = [];
    for (const entry of selectors) {
      document.querySelectorAll(entry.selector).forEach((node) => {
        items.push({ node, role: entry.role });
      });
    }
    return sortInDomOrder(items);
  }

  function extractGeminiMessages() {
    const items = [];
    document.querySelectorAll("user-query").forEach((node) => {
      items.push({ node, role: "user" });
    });
    document.querySelectorAll("model-response").forEach((node) => {
      items.push({ node, role: "assistant" });
    });
    return sortInDomOrder(items);
  }

  function extractGenericMessages() {
    const items = [];
    const candidates = [
      { selector: "[data-message-author-role]", role: null },
      { selector: "[data-testid*='message']", role: null },
      { selector: "main article", role: "assistant" }
    ];

    for (const candidate of candidates) {
      document.querySelectorAll(candidate.selector).forEach((node) => {
        const inferredRole = candidate.role
          || node.getAttribute("data-message-author-role")
          || node.getAttribute("data-testid")
          || "assistant";
        items.push({ node, role: inferredRole });
      });
    }

    return sortInDomOrder(items);
  }

  const site = inferSite(location.hostname);
  let rawItems = [];

  if (site === "chatgpt") {
    rawItems = extractChatGptMessages();
  } else if (site === "claude") {
    rawItems = extractClaudeMessages();
  } else if (site === "gemini") {
    rawItems = extractGeminiMessages();
  }

  if (!rawItems.length) {
    rawItems = extractGenericMessages();
  }

  const messages = uniqueByNodeAndText(rawItems);
  if (!messages.length) {
    return {
      ok: false,
      error: "没有在当前页面识别到聊天消息。请先打开具体的对话页面，再点击扩展按钮。"
    };
  }

  const firstUser = messages.find((message) => message.role === "user");
  const fallbackTitle = firstUser ? firstUser.content.slice(0, 36) : "未命名会话";
  const cleanedTitle = cleanTitle(document.title);

  return {
    ok: true,
    conversation: {
      title: cleanedTitle === "未命名会话" ? fallbackTitle : cleanedTitle,
      site,
      sourceUrl: location.href,
      capturedAt: new Date().toISOString(),
      messages
    }
  };
}
