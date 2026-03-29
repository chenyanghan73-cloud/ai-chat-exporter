# AI 聊天记录导出 PDF

这是一个本地 Windows 小工具，用来把 ChatGPT、Claude、Gemini 等 AI 聊天记录整理成 PDF 文档，方便你在换账号、做归档、二次喂给模型时继续使用。

当前版本已经做成可直接运行的本地工具：

- 图形界面启动文件：`启动聊天记录导出器.bat`
- 主程序：`chat_archive_pdf_tool.py`
- 示例输入：`sample_chat.txt`
- 示例输出：`output/sample.pdf`

## 功能

- 导入 `ChatGPT conversations.json`
- 导入通用 `role/content` JSON
- 导入带角色标记的 `txt` / `md`
- 导出为排版清晰的 `PDF`
- 同时导出 `Markdown`，方便后续重新喂给大模型
- 支持批量导出多会话

## 支持的输入格式

### 1. ChatGPT 导出的 `conversations.json`

如果你从 ChatGPT 账号导出了完整聊天记录，这个工具会自动识别出多个会话，并允许你单独导出或批量导出。

### 2. 通用 JSON

支持这种常见结构：

```json
[
  { "role": "user", "content": "你好" },
  { "role": "assistant", "content": "你好，有什么我可以帮你？" }
]
```

也支持这种带 `messages` 包裹的结构：

```json
{
  "title": "示例会话",
  "messages": [
    { "role": "user", "content": "帮我整理一下这段对话" },
    { "role": "assistant", "content": "可以，我们先提炼重点。" }
  ]
}
```

### 3. `txt` / `md`

推荐使用这种写法：

```text
用户: 我想把对话留档
助手: 可以，我帮你整理成 PDF

用户: 还想保留 Markdown
助手: 没问题，这样更适合二次投喂模型
```

支持的角色前缀包括：

- `用户:`
- `我:`
- `User:`
- `Assistant:`
- `助手:`
- `ChatGPT:`
- `Claude:`
- `Gemini:`
- `系统:`
- `System:`

## 怎么用

### 方式一：图形界面

1. 双击 `启动聊天记录导出器.bat`
2. 点击“导入文件”选择你的聊天记录
3. 在左侧选择一个会话
4. 点击“导出当前会话 PDF”或“批量导出全部”

默认会额外导出一份 `.md` 文件。

### 方式二：命令行

导出单个文本会话：

```powershell
python .\chat_archive_pdf_tool.py --input .\sample_chat.txt --output .\output\sample.pdf --markdown
```

批量导出 ChatGPT `conversations.json`：

```powershell
python .\chat_archive_pdf_tool.py --input .\conversations.json --output .\output\all_chats --all --markdown
```

## 输出内容

- `PDF`：适合归档、打印、长期保存
- `Markdown`：适合以后继续发给 AI，当作上下文继续使用

## 说明

- 当前工具面向 Windows
- 已在本目录内放入本地依赖 `.deps`
- 如果导入的是中文文本，程序会自动尝试 `utf-8`、`utf-8-sig`、`gb18030`、`gbk`
- 如果以后你想升级成“浏览器一键抓当前 ChatGPT 页面并直接导出”的插件版，这个项目也可以继续往那个方向扩展

## 浏览器扩展版

当前目录里已经新增扩展版：

- `browser-extension/manifest.json`
- `browser-extension/popup.html`
- `browser-extension/popup.js`
- `browser-extension/preview.html`
- `browser-extension/README.md`

它支持在 ChatGPT / Claude 页面直接抓取当前会话，然后：

- 打开打印预览页
- 自动唤起浏览器打印
- 下载 Markdown
- 下载 JSON
- 复制纯文本

注意：

- 浏览器安全限制决定了扩展不能静默保存 PDF
- 当前实现会尽量接近一键导出，但最后一步仍需要你在打印目标中选择“另存为 PDF”
