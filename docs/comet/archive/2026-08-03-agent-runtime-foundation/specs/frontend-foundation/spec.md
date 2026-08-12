# 前端基础完整目标规格

## 1. 技术与部署基线

VenAgent SHALL 保持根目录 `web/` 的 Vue 3、TypeScript、Vite、Pinia 与 Vue Router 基线。开发期通过 Vite 同源代理访问 `/api` 与 `/health`；生产构建位于 `web/dist` 并由 FastAPI 托管，缺少构建产物时不得伪装前端可用。

应用继续使用单一工作型聊天界面，不新增 landing page、用户中心、工具中心、记忆中心或未来模块空路由。

## 2. 前端状态所有权

- Pinia SHALL 分离正式 `ConversationMessage`、`AgentRunProjection`、以 run ID 为键的 `PartialStreamState`、当前 owner/对话选择和纯 UI 状态。
- 服务端正式 messages 与 run snapshot 是权威事实；partial 仅存在当前页面内存，不写 localStorage、不上传、不进入正式上下文。
- selector 根据显式 conversation/message/run IDs 生成线性时间线；组件不得按文本相同、数组相邻或 DOM 位置猜测关联。
- 发送时不得预造正式 assistant message。创建事务确认后展示 user message 与 run 区域；成功后用服务端 assistant message完整替换 partial。
- 当前不提供重新生成成功回答、回答版本或分支。多个失败/取消/不兼容尝试默认折叠为“此前有 N 次尝试”，按需展开安全摘要。

## 3. 创建、观察与恢复

- 发送先 `POST /api/conversations/{conversation_id}/runs`，获得 202、run ID 和 input message ID；再连接 run SSE。
- SSE 首个 snapshot SHALL 原子替换该 run 的权威投影；后续 status/progress/token/terminal 仅在 owner、conversation 和 run 全部匹配时应用。
- token 只追加到 reactive partial。实现 SHALL 通过 collection 中的 reactive 引用或稳定 ID 定位更新，不能持有绕过 Vue proxy 的旧对象引用。
- SSE 断开、页面刷新或关闭不发送隐式 cancel。页面可显示“后台继续”，重连先查询/snapshot；SSE 不可用时退化为有界轮询同一 run projection。
- completed 后读取正式 assistant message并清除 partial；failed/cancelled/incompatible 收敛操作状态，partial 不能伪装为历史。
- 响应 EOF、读取异常或活动超时且没有终态时只标记观察连接中断；run 本身仍由查询决定，不得永久 busy 或自动失败/取消。

## 4. 用户操作与错误状态

- 用户可创建、选择、改名、删除 conversation，发送消息，观察后台运行，显式取消，查看安全进度，并在动态 `retry_eligible` 为 true 时 retry。
- retry 使用原 run endpoint并获得新的 run ID；网络不确定时先对账，不能无条件重发。成功回答不显示 retry/regenerate。
- 界面分别处理 loading、empty、queued、running、waiting approval 占位、succeeded、failed、cancelled、incompatible、connection interrupted、offline、401、403/404、409、429 与 503。
- `404` 安全错误只移除当前 owner对应的无效引用；普通网络/模型/取消错误不得删除 conversation。
- 取消按钮只触发显式 cancel API。终态、身份变化或 conversation 删除后立即禁用旧操作并清理观察资源。

## 5. 身份与缓存

- 身份 bootstrap 完成前显示稳定加载态，不先渲染错误 owner 数据。
- 身份变化、跨标签页失效通知或 owner删除时，立即停止旧观察、隐藏/清除旧 owner messages/runs/partial，再重新确认身份。
- 同源标签页只广播非敏感“身份需要确认”信号，不传 JWT、Cookie、用户名、message、run 或 partial 内容。
- 正式服务端数据 MAY 做 owner-keyed视图缓存，但不得把未完成 partial 当恢复依据；显式 logout 清旧 owner缓存。
- temporary 模式明确说明匿名可用、持久化不可用、重启丢失；账号操作使用统一不可用 modal。

## 6. 流式渲染与滚动

- 每个当前 run 的非空 token 到达后 SHALL 立即更新 reactive DOM，在 completed 前可观察至少两个不同非零文本长度；不得用假打字定时器替代真实 SSE。
- completed answer/message与 partial 对账，以服务端正式消息为最终值。
- 聊天工作区固定在动态视口高度，只有消息区纵向滚动，composer在桌面和移动端始终可见。
- 当用户位于命名的底部阈值内，新增 message/token/终态在 Vue DOM 更新后自动跟随；用户向上离开阈值后不得强拉，手动回到底部后恢复。
- 高频 token 的滚动请求最多保留一个 animation frame；切换对话、身份变化和卸载时清理 reader、timer、AbortController、listener 与 pending frame。
- 自动跟随只滚消息容器，不滚 window、不改变焦点；当前 run busy 不得让 Enter 意外触发取消。

## 7. 视觉与可访问性

- 保持浅色、低噪声工作台；宽屏左侧 conversation 导航、中央对话区，窄屏导航为可访问抽屉。
- queued/running/waiting/terminal 状态在 user message下使用紧凑内联区域，不创建层层嵌套卡片或长期占据时间线的 run 卡片。
- 抽屉、modal、取消、retry 和状态控件支持键盘顺序、Escape、焦点陷阱/恢复、屏幕阅读器名称和 390px 视口。
- 长文本、长标题、错误文案和多次尝试不得溢出、遮挡 composer 或导致 incoherent overlap。

## 8. 安全与隐私

- 所有外部文本按安全纯文本边界渲染，不使用未净化 HTML；错误不显示 Prompt、State、凭据、连接串或栈。
- 不新增分析、追踪像素、第三方脚本或外部数据接收方。
- 迟到 token、旧 run 事件和跨 owner数据必须丢弃；partial 不得写浏览器持久缓存或回传服务端。

## 9. 验收

- typecheck、build、组件/单元测试通过，Vite proxy 与 FastAPI production build 均可完成真实后端主路径。
- 可控分段 SSE 证明 completed 前渐进渲染、snapshot 收敛、无终态断线只影响观察、刷新后后台继续和最终正式消息替换。
- 浏览器自动化与人工验收覆盖发送、取消、失败 retry、多个尝试折叠、迟到事件、owner切换、404/409/429/503、temporary 降级、桌面与 390px 抽屉/滚动。
- Verify 检查浏览器控制台、网络请求、重复消息、观察资源泄漏和前后端协议错配；发现问题必须修复并重新执行受影响流程。
