# 前端基础迁移

## 目标

VenAgent SHALL 将当前单文件聊天页面迁移为根目录 `web/` 下可独立开发、按 feature 组织的 Vue 前端，同时保持现有 FastAPI 聊天、SSE、线程和持久化降级契约。

## 技术与部署边界

- 前端 SHALL 使用 Vue 3、TypeScript、Vite、Pinia 和 Vue Router。
- 源码 SHALL 按 `app/`、`modules/`、`shared/` 与 `assets/` 组织；聊天状态、SSE 和会话交互属于 `modules/chat`。
- 开发期 SHALL 通过 Vite 代理同源访问 `/api`、`/health` 和运行取消端点。
- 初期生产构建产物 SHALL 位于 `web/dist`，由 FastAPI 托管；构建产物不存在时服务不得伪装为可用的前端部署。
- 前端 SHALL 不持有业务真相源；Pinia 仅保存视图、当前已验证 owner 的 server thread 缓存和在途运行状态，不提供独立本机历史。

## 视觉与信息架构

- 应用 SHALL 使用浅色、低噪声的工作台视觉：宽屏左侧为会话导航，中央为对话工作区。
- 会话导航 SHALL 在窄屏收起为可访问的抽屉，并提供键盘操作与焦点恢复。
- 组件 SHALL 提供清晰的空态、加载态、思考态、生成态、失败态、取消态、中断态和持久化降级态。
- 本 change 可以重做布局、色彩、排版与组件样式，但不 SHALL 增加身份、偏好、文档、任务或其他后续模块的页面、菜单或数据模型。

## 行为等价

- 用户 SHALL 能创建和删除对话；删除当前对话后维持现有的活动会话选择语义。
- 用户 SHALL 能发送消息、逐 token 读取 SSE、取消在途运行并重试失败消息。
- 浏览器 SHALL 为当前已验证 owner 保留未完成运行的恢复或失败标记语义；身份变化时 SHALL 清除上一 owner 缓存。
- 页面 SHALL 读取 `/health` 并正确区分持久化可用与进程内降级。
- 后端返回 `thread_not_found` 后，前端 SHALL 从列表和浏览器缓存移除该 thread 引用并显示一次“对话已不存在”提示，不得转为 `local_only`、恢复或导入。
- 前端 SHALL NOT 显示“本机历史”“仅本地”或对应只读会话入口。
- HTTP、SSE、健康检查和取消接口的 URL、请求与响应语义不 SHALL 因此前端迁移而改变；前端 SHALL NOT 调用旧会话导入接口。

## 流式状态与终止收敛

- 请求发出但尚未收到 `started` 时，用户消息 SHALL 显示“发送中”；收到 `started` 后用户消息视为已发送，assistant 在首个 `token` 前显示“思考中”，首个 token 后显示“生成中”。
- 用户主动停止后，assistant SHALL 显示“已停止生成”，用户消息不得显示“发送失败”；已收到 partial 可以保留并由用户显式重新生成。
- 前端 SHALL 记录是否收到 `completed|cancelled|error`。响应 EOF、读取异常或活动超时发生且尚无终态时，当前尝试 SHALL 收敛为“连接已中断”并允许显式重试，不得永久停留在发送/思考/生成状态。
- 后端 MAY 发送不改变业务事件序号的 SSE heartbeat；前端 SHALL 以任意有效数据块或 heartbeat 刷新活动计时，并在结束时释放 reader、timer、AbortController 与 thread stream 状态。
- 重试 SHALL 复用原 `client_message_id`，成功后与服务端 committed turn 收敛为唯一 user/assistant 对。

## 身份与多标签页

- 同源标签页只可广播非敏感的身份失效通知，不得广播 access token、refresh 凭据、Cookie、用户名或消息内容。
- 接收身份失效通知的标签页 SHALL 立即停止活动读取、隐藏并清除旧 owner 缓存，再通过 HttpOnly refresh Cookie 重新确认身份。
- 登录、注册、退出、注销和 401 降级 SHALL 使用同一身份转换入口；身份栏与聊天内容不得出现不同 owner 的混合状态。

## 视口与长文本

- 聊天工作区 SHALL 固定在动态视口高度内，标题、状态、消息和输入区形成稳定网格；只有消息区域纵向滚动，composer 在桌面和移动端始终保持在视口内。
- 长文本生成期间，用户接近消息区底部时 MAY 自动跟随；用户主动向上滚动后不得强制拉回。
- 生成期间输入框 SHALL 保持可见。停止命令由明确的停止按钮触发，输入框 Enter 不得因当前 busy 状态意外取消运行。

## 安全与隐私

- 前端不 SHALL 引入分析、追踪像素、第三方脚本或新的外部数据接收方。
- 错误呈现不得显示凭据、连接串或内部堆栈。
- 所有来自浏览器本地存储和 HTTP/SSE 的数据 SHALL 在显示前保持现有的安全文本渲染边界。
- 本机失败、取消或 partial 缓存不得上传、重建或伪装成有效后端上下文；身份变化后不得继续显示旧 owner 内容。

## 验收

- Vite 构建通过，且 Vite 开发服务可经代理完成聊天主路径。
- FastAPI 在构建产物存在时提供前端，在缺失时返回明确、可测试的行为。
- 浏览器自动化覆盖创建、流式、无终态 EOF、取消、重试、删除、身份切换、同源双标签退出/注销、持久化降级，以及桌面和移动端长文本 composer 可见性。
- 现有 Python API、SSE 与持久化回归测试保持通过。
- 后续产品模块不得在 `frontend-foundation` 归档前进入 Build。
