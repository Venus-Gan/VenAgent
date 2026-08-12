# Outcome

实现 M04 `ownership-lifecycle`：为 VenAgent 引入可选身份、权威 `owner_id`、跨用户数据隔离、账户删除与数据保留生命周期，使后续按用户存储或访问数据的模块拥有可验证的授权边界。

# Scope

- 定义身份状态、认证入口、当前用户读取、授权失败语义和所有权传播的完整产品契约。
- 为 conversation thread、legacy import 与相关 checkpoint 明确 owner 归属、服务端校验和历史未归属数据的迁移/可见性规则。
- 定义账户删除的确认、执行、数据处理、失败恢复和用户可见反馈。
- 为现有 Vue 聊天工作区定义最小身份/匿名、隔离、无权、删除、失败与持久化降级体验。
- 记录 API、配置、持久化、可观测性、测试和安全验收要求；实现位置在用户确认后再决定。

# Non-goals

- 不实现 M05 记忆、M06 工具执行、M07 编排、M08 RAG 或 M09 平台治理能力。
- 不恢复 M03A 的会话标题、文件夹、归档、分叉、备份导入导出或跨设备历史同步。
- 不迁移 AGI-saber 的 Go 代码、数据表、JWT 方案或其前端 token 存储方式。
- 不在未确认前选择第三方身份提供商、token 载体、密码哈希库、数据保留时长或目录树。

# Acceptance examples

- 已登录用户只能创建、读取、聊天、导入或删除自己拥有的 thread；猜测其他用户的 `thread_id` 不得获得数据、运行控制或删除能力。
- 匿名模式的创建、聊天、取消、删除和前端失败/降级呈现符合已确认的产品选择，且不会把匿名 thread 误归属给其他用户。
- 注册/登录、失效凭据、退出或身份服务不可用均返回稳定且不泄露凭据或账户存在性的错误语义；前端清楚呈现可恢复操作。
- 用户触发账户删除后，其数据按已确认的保留策略处理；删除中、失败、重试与完成状态可审计，且不会留下可访问的孤儿 thread/checkpoint。
- PostgreSQL durable 与 memory degraded 模式都准确表达身份和所有权能力边界；不得把无权或不可用伪装为成功。

# Constraints and invariants

- `thread_id`、`run_id` 与 `owner_id` 分别表示对话隔离、运行身份和数据所有权，不得互用。
- 授权必须在服务端业务边界执行；HTTP 路由只做请求/响应映射，`infra/` 不承载 feature use case。
- 业务用例不得依赖具体认证、令牌、数据库或浏览器 adapter；配置、密钥和凭据不得出现在源码、日志、错误、brief 或测试证据中。
- 持久化运行中发生数据库故障时不得静默改为另一份内存所有权状态；memory degraded 行为必须按最终契约显式说明。
- 当前 `conversation/`、`agent/`、`infra/`、`interfaces/http/` 和 `web/src/modules/chat/` 是事实边界，不预建未来 package、共享层、菜单或路由。
- 认证、授权、用户输入、删除和外部配置需要 Pydantic 边界校验、参数化数据库访问、稳定安全错误、授权测试与审计/观测边界。

# Decisions

- M04 是 M05 及一切按用户存储或访问的数据能力的前置条件。
- `frontend-foundation` 已归档，M04 可在其批准后扩展既有 Vue 工作区或新增最小表面。
- 当前实现没有身份层：thread 以 UUID 为唯一访问依据，PostgreSQL `conversation_threads` 没有 `owner_id`，memory store 只保存生命周期状态。
- AGI-saber 仅作为行为事实来源。可采用统一认证失败、弱密钥配置拒绝、请求级身份上下文和服务端 owner 校验；不采用其 Go 架构、表结构或 Bearer token 的前端存储方式。
- 模块 intake：已读取 `ecc-rules-pack-common`、`ecc-rules-pack-python`、`search-first`、`api-design`、`security-review` 和 `product-capability`。
- search-first：仓库检索、已安装依赖与 npm 可用性已检查；npm 11.6.0 与项目 pip 可用，现有 Python 环境没有 pwdlib、passlib、PyJWT、python-jose 或 bcrypt；GitHub CLI 未安装；官方资料检索通道返回服务端 404，未作为“未找到”结论。当前为 `Build`（待产品选择后，以最小依赖实现或有证据地采用依赖）的暂定结论。
- AGI-saber：优先路径实际位于 `internal/domain/auth`、`internal/application/auth`、`internal/usercontext`、`internal/infrastructure/persistence/userrepo`；因 HTTP 调用与测试需要，最小扩展到 `internal/interfaces/http/middleware`、相关 handler 检索及认证测试。理由是确认请求身份传播、401 语义与 owner 隔离风险；未扫描其余旧项目。
- AGI-saber 前端对照：其 `AuthModal` 提供 Tab 式登录/注册，`SideBar` 显示用户名与登出，入口以未登录即阻断的全屏覆盖层实现。VenAgent 可采用其清晰的表单状态、处理状态和错误反馈，不采用强制覆盖层或其 JWT `localStorage` 存储；前者与已确认的匿名使用冲突，后者与服务端 Cookie 会话冲突。
- 目录（product-capability）：能力覆盖身份与聊天工作区；当前相关位置为 `conversation/`、`infra/platform/`、`interfaces/http/`、`infra/config/` 和 `web/src/modules/chat/`。实现前须确定是扩展现有 conversation 还是新增最小身份 feature；不预建 M05+ 共享用户/权限框架、管理 UI、角色系统、外部 SSO 或固定目录树。
- 前端：最小操作为选择匿名或登录、查看身份与数据状态、完成登录/退出、处理无权/失效/不可用，并确认账户删除；需覆盖正常、加载、失败、降级和无权状态，以及浏览器主路径。
- 用户确认 Q1（1A）：允许匿名使用；为浏览器建立受服务端校验的匿名归属，登录后仅可由用户显式确认将该浏览器的匿名对话归属到账号。
- 用户确认 Q4（3A）：账户删除经确认后立即永久删除账户及其拥有的数据；不提供撤回保留期。
- 用户确认 Q2（2A）：首版采用本地用户名/密码认证和服务端安全会话 Cookie；不接入第三方 SSO 或邮件魔法链接。Cookie 只保存高熵、不透明的会话凭据，服务端只保存其哈希。
- 用户确认 Q3（C）：M04 升级时删除全部无 `owner_id` 的既有 durable thread 及其关联持久化状态；旧浏览器记录仅本地只读保留，不上传、不认领。该清理不影响 M04 上线后通过受服务端校验的匿名所有者认领对话。
- 数据模型文档：拟议 `ownership-lifecycle` 规格必须维护 owners、users、auth_sessions、guest_sessions 与 conversation_threads 所有权字段的职责、字段、约束、索引、迁移、认领和删除顺序，作为后续维护的权威说明。
- 用户确认 Q4（A）：PostgreSQL 未配置、不可用或 schema 不可用时，保持现有进程内匿名聊天可用；账号注册、登录、匿名认领和账户删除不可用并返回稳定的身份基础设施不可用语义。重启后匿名后端上下文失效，前端必须明确说明。用户尝试创建账号时，前端 SHALL 弹窗说明 PostgreSQL 当前不可用，用户模块不可用，且不得伪装为已创建账号。
- 用户确认 Q5（C）：账户入口常驻现有左侧会话栏；匿名状态提供登录/注册操作，登录状态显示用户名、匿名对话认领、登出和账户删除入口。窄屏时该面板随可访问会话抽屉打开，关闭和焦点恢复遵循现有侧栏行为。
- 目录决策（product-capability）：新增 `venagent/ownership/` 承载 M04 的身份、会话、所有者、认领和删号用例及其消费方端口；`conversation/` 只扩展为显式接收并校验 `owner_id`，不得反向依赖认证 adapter。`infra/platform/` 增加 PostgreSQL/内存 ownership adapter 与 M04 migration，`infra/config/` 增加认证秘密配置，`interfaces/http/` 增加薄的 ownership HTTP 映射，`web/src/modules/ownership/` 承载左侧账户面板与弹窗状态，`web/src/modules/chat/` 只组合该面板与聊天状态。新增测试分别位于 `tests/` 与 `web/tests/e2e/`。不创建通用 `auth/` 平台层、RBAC、组织/团队、管理后台、SSO provider 或未来模块共享 UI。
- 用户确认：完整 M04 目标规格、维护数据模型、最小目录增量、匿名与账号生命周期、降级行为、左侧账户 UI 及验收要求均已确认，可进入 Build。

# Open questions

- 无。

# Verification expectations

- 使用无网络、无真实凭据的单元与 API 集成测试，覆盖身份状态、输入边界、认证失败、owner 隔离、跨线程/跨用户拒绝、删除、重试与持久化失败关闭。
- 使用临时隔离数据库验证迁移、owner 约束、历史数据策略、删除与恢复；不得依赖真实生产数据库或密钥。
- 验证 FastAPI schema/依赖/错误映射、配置 fail-closed 行为、秘密不泄露及健康/降级可见性。
- 验证 Vue 的正常、加载、失败、降级和无权状态；构建与浏览器自动化覆盖已确认的身份主路径，并保持现有 Python、SSE、取消与持久化回归通过。
