# AI Chat Exporter 浏览器扩展

这是一个可加载到 Chrome 或 Edge 的本地扩展。

功能：

- 在 ChatGPT / Claude 页面抓取当前会话
- 打开排版好的打印预览页
- 自动唤起浏览器打印
- 下载 Markdown
- 下载 JSON
- 复制纯文本

## 安装方法

### Edge

1. 打开 `edge://extensions/`
2. 开启“开发人员模式”
3. 点击“加载解压缩的扩展”
4. 选择当前目录下的 `browser-extension` 文件夹

### Chrome

1. 打开 `chrome://extensions/`
2. 开启“开发者模式”
3. 点击“加载已解压的扩展程序”
4. 选择当前目录下的 `browser-extension` 文件夹

## 使用方法

1. 进入 ChatGPT 或 Claude 的具体聊天页面
2. 点击浏览器工具栏上的 `AI Chat Exporter`
3. 选择：
   - `打印为 PDF`
   - `下载 Markdown`
   - `下载 JSON`
   - `复制纯文本`

## 关于 PDF

浏览器扩展不能绕过浏览器的安全限制直接静默保存 PDF，所以当前实现是：

1. 抓取当前会话
2. 打开排版好的打印预览页
3. 自动唤起浏览器打印
4. 你在打印目标里选择“另存为 PDF”

这已经接近一键导出，同时兼容 Chrome / Edge 的正常安全模型。

## 兼容性说明

- 已优先适配：`chatgpt.com`、`chat.openai.com`、`claude.ai`
- `gemini.google.com` 做了实验性支持
- 如果页面结构将来变化，可能需要更新抓取选择器
