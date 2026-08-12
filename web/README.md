# VenAgent Web

`web/` 是 VenAgent 的 Vue 3 + TypeScript + Vite 前端。开发期由 Vite 将 `/api` 和 `/health` 代理到 FastAPI；生产初期由 FastAPI 托管 `web/dist`。

## 常用命令

在本目录运行：

```powershell
npm.cmd run dev
npm.cmd run build
npm.cmd run test:e2e -- --reporter=line
```

`test:e2e` 配置为使用本机安装的 Google Chrome，而非 Playwright 下载的 Chromium。

## 本地 UI 验收

每次影响布局、交互或响应式行为的改动，按以下顺序验收：

1. 运行 `npm.cmd run build`，确认 TypeScript 检查和生产构建通过。
2. 运行 `npm.cmd run test:e2e -- --reporter=line`，允许测试进程启动本机 Chrome。
3. 以 Chrome 检查以下视口：桌面 `1440x900`、移动端 `390x844`，以及移动端展开会话抽屉后的状态。
4. 检查页面没有控制项拉伸、文本溢出或互相遮挡；输入区固定在视口底部；发送按钮保持稳定尺寸；移动端抽屉可打开、关闭并遮罩工作区。

浏览器验收脚本必须关闭它创建的 Chrome 和 Vite 服务，避免保留后台进程或占用 `4173` 端口。

## Chrome 与 Codex

优先使用 Codex 的 ChatGPT Chrome Extension 进行可见 UI 操作。它依赖以下条件：

- Google Chrome 已安装并运行。
- ChatGPT Chrome Extension 已安装且启用。
- Chrome Native Messaging Host 注册正确。

扩展无法连接时，先检查扩展状态。若扩展已启用但 Native Messaging Host 缺失或无效，从 Codex/ChatGPT 的插件管理界面重新安装插件；不要手工修改注册表或 native-host 文件。

插件不可用时，使用 Playwright 的 `channel: 'chrome'` 回退。该方式仍使用本机 Chrome，但以独立临时 profile 启动，不读取或修改日常 Chrome 会话。

## 常见故障

| 现象 | 原因与处理 |
| --- | --- |
| `Browser is not available: extension` | Chrome 插件未连接。确认扩展与 native host；必要时从插件管理界面重装。 |
| `Crashpad`、profile lock 权限错误，或 `0xC0000409` | Chrome 在受限终端内无法访问 profile 或系统资源。以允许 GUI/浏览器启动的执行上下文重跑 Playwright；这通常不是页面或 Vite 故障。 |
| 临时 PowerShell 验收脚本找不到中文文本 | 管道内容可能发生转码。临时脚本使用 CSS、ARIA 或英文结构选择器，不依赖中文可见文本。 |
| 抽屉截图只显示一部分 | 截图发生在 CSS 动画期间。等待当前 `160ms` 过渡完成后再截图。 |
| `4173` 已被占用 | 停止遗留的 Vite 进程，或让 Playwright `webServer` 复用已有服务。 |

## UI 基线

- 宽屏：左侧会话导航，右侧对话工作区。
- 窄屏：导航为可访问抽屉；支持菜单按钮、关闭按钮、遮罩点击和 Escape。
- Composer：初始为单行，按内容增长至最大高度；只有溢出时显示滚动条。发送按钮固定为 `48px`，不得因 flex 或 grid 的 stretch 行为扩大。
- 验收以真实本机 Chrome 为准；自动化断言验证行为，截图复核视觉比例与响应式布局。
