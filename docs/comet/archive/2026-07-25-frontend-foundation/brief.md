# Outcome

将当前单文件聊天 Web UI 迁移为根目录 `web/` 下的 Vue 3 + TypeScript + Vite + Pinia + Vue Router 工程，使后续模块能按前端 feature 演进，同时保持当前聊天行为和 FastAPI API 契约。

# Scope

- 新建独立前端工程及开发期 Vite 代理。
- 迁移当前会话创建/删除、SSE 流式、取消、重试、本地记录、持久化可用性或降级提示和旧会话导入。
- 调整 FastAPI 以在生产初期托管前端构建产物，并保留无构建产物时的明确启动行为。
- 为关键浏览器路径提供自动化验证。

# Non-goals

- 不实现 M04 身份、owner 隔离或任何后续产品模块。
- 不改变现有 HTTP、SSE、健康检查或浏览器本地数据的业务语义。
- 不引入独立前端部署、CDN、分析脚本或第三方数据接收方。

# Acceptance examples

- 用户能在 Vite 开发服务中创建和删除对话，并通过代理使用现有 FastAPI API。
- 用户发送消息后能看到逐 token 流式输出；发送后可取消；失败后可重试。
- 未配置或不可用持久化时，页面显示进程内上下文的降级说明；持久化可用时保留现有跨重启说明与旧会话导入行为。
- 生产构建产物存在时，FastAPI 提供该前端；构建产物缺失时，不伪装成可用的前端部署。

# Constraints and invariants

- 前端源代码位于仓库根 `web/`，按 `app`、`modules`、`shared` 分层；聊天状态属于 `modules/chat`。
- FastAPI 仍是业务事实源；Pinia 只持有视图、本地记录和在途运行状态。
- 开发期通过同源 Vite 代理访问 `/api`、`/health` 和运行取消端点；生产初期由 FastAPI 托管 `web/dist`。
- 保持可访问的键盘发送、焦点管理、按钮标签和错误/降级状态。

# Decisions

- search-first 结论：采用 Vue 3、Vite、Pinia、Vue Router 和 TypeScript；为现有 FastAPI/SSE 契约编写薄适配层，不引入新的后端协议。
- 当前仓库和 AGI-saber 证明 Vue/Vite/Pinia 适合目标；AGI-saber 仅作组件和状态拆分参考，不迁移其 JavaScript、认证或业务实现。
- 选择 B：本 change 同时重整应用壳与设计基础，包括整体布局、色彩和排版、组件规范、加载/失败/降级状态、响应式与键盘/焦点体验；不实现身份、偏好、文档或其他 M04+ 能力。
- 选择 A：采用浅色、低噪声的工作台。宽屏为左侧会话导航加中央对话工作区；移动端侧栏收起为可访问的抽屉。视觉重整不增加未来模块的页面、菜单或数据模型。

# Open questions

- 已确认：本 change 在根目录 `web/` 建立 Vue 3 + TypeScript + Vite + Pinia + Vue Router 前端，重整为浅色工作台并等价保留现有聊天功能；生产初期由 FastAPI 托管构建产物，`frontend-foundation` 归档后才进入 M04。它不实现 M04+ 产品功能、独立部署或后端协议变更。

# Verification expectations

- 验证 TypeScript 构建、FastAPI 静态托管、现有 Python 回归测试和浏览器关键路径。
- 记录 search-first 的可用渠道、未使用渠道及 Adopt/Extend/Compose/Build 决定。
