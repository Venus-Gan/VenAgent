# 所有权与身份生命周期

## 1. 目标与边界

VenAgent SHALL 提供可选身份、权威 `owner_id`、服务端授权和账户数据生命周期。匿名访客与注册用户都可以拥有对话；已登录用户只能访问自己的数据。M04 是后续按用户存储或访问数据能力的前置条件。

本模块不实现第三方 SSO、邮件魔法链接、角色系统、组织/团队、M05+ 数据域、会话资料管理或 M03A 已放弃的历史管理功能。

## 2. 身份与会话

- M04 SHALL 提供本地用户名/密码注册和登录；密码只可存储为不可逆哈希，不得写入日志、错误响应或浏览器存储。
- 登录和匿名访问 SHALL 分别使用独立、高熵、不透明的 Cookie 凭据。浏览器不得保存 JWT、会话原值或密码到 `localStorage`。
- 服务端 SHALL 只保存 Cookie 凭据的哈希，且为缺失、失效、撤销或格式非法的凭据返回稳定且不泄露账户存在性的错误。
- 每个 HTTP 请求 SHALL 在进入 conversation 用例前解析出当前匿名或用户所有者；所有权检查必须在业务边界执行，而非只依赖前端隐藏或 UUID 不可预测性。
- 匿名访客登录后 SHALL 仅在用户显式确认时认领该浏览器当前访客所有者的对话。认领 SHALL 原子地把对话所有者迁移到当前用户，并撤销原访客会话；不得通过任意 `thread_id` 认领别人的数据。

## 3. 维护数据模型

本节是 M04 数据库 schema、迁移、运维排查和后续模块扩展的权威说明。表名是逻辑职责；实际 Python package 或 adapter 位置由 Build 在当前目录边界内最小化决定。

### 3.1 `owners`

| 字段 | 约束 | 含义 |
|---|---|---|
| `owner_id` | UUID，主键 | 跨数据域稳定的内部所有者标识；对话只关联此字段。 |
| `kind` | `guest` 或 `user` | 所有者类型。 |
| `created_at` | 非空时间戳 | 创建和审计时间。 |

此表是匿名与注册用户共用 `conversation_threads.owner_id` 外键的最小模型，不是为未来角色、组织或权限系统预建的平台抽象。

### 3.2 `users`

| 字段 | 约束 | 含义 |
|---|---|---|
| `owner_id` | UUID，主键，外键至 `owners.owner_id` | 注册用户对应的所有者；仅允许 `owners.kind=user`。 |
| `username_normalized` | 非空、唯一 | 经过稳定规范化后用于登录和重复检查的用户名。 |
| `username_display` | 非空 | 保留供界面显示的用户名形式。 |
| `password_hash` | 非空 | 不可逆密码哈希，绝不保存明文。 |
| `created_at` | 非空时间戳 | 注册时间。 |

`username_normalized` SHALL 具备唯一索引。用户查找、密码校验和账号枚举防护必须使用稳定错误语义。

### 3.3 `auth_sessions`

| 字段 | 约束 | 含义 |
|---|---|---|
| `session_id` | UUID，主键 | 一次账号登录会话的内部标识。 |
| `user_owner_id` | UUID，外键至 `users.owner_id` | 会话所属注册用户。 |
| `secret_hash` | 非空、唯一 | Cookie 中随机会话凭据的哈希。 |
| `expires_at` | 非空时间戳 | 会话到期时间。 |
| `revoked_at` | 可空时间戳 | 退出、删除账户或安全撤销后的时间。 |

有效会话查找 SHALL 使用 `secret_hash`、未撤销状态和到期时间；账号删除 SHALL 撤销或删除全部账号会话。

### 3.4 `guest_sessions`

| 字段 | 约束 | 含义 |
|---|---|---|
| `guest_owner_id` | UUID，主键，外键至 `owners.owner_id` | 浏览器匿名访客的所有者；仅允许 `owners.kind=guest`。 |
| `secret_hash` | 非空、唯一 | 匿名 Cookie 中随机凭据的哈希。 |
| `expires_at` | 非空时间戳 | 访客身份及其可认领对话的到期时间。 |

访客 Cookie 丢失、失效或撤销后，不得凭 `thread_id` 恢复或认领访客数据。

### 3.5 `conversation_threads` 的所有权扩展

| 字段 | 约束 | 含义 |
|---|---|---|
| `owner_id` | UUID，外键至 `owners.owner_id` | thread 的唯一权威所有者。 |

新创建、聊天、流式运行、取消、legacy import、读取状态和删除 SHALL 按当前请求 `owner_id` 校验。查询和更新 SHALL 同时以 `thread_id` 与 `owner_id` 限定；不得先按 thread 查询再把授权留给调用方。`owner_id` SHALL 建立与生命周期查询相匹配的索引。

## 4. 迁移、认领与删除

- M04 数据库迁移 SHALL 先创建身份与所有者表，并以兼容步骤添加 `conversation_threads.owner_id`。
- 所有 M01--M03 遗留、无 `owner_id` 的 durable thread 及关联持久化状态 SHALL 在升级中删除；旧浏览器记录保持本地只读，不上传、导入或认领。
- 清理完成并验证无未归属数据后，新的 durable thread SHALL 使用非空 `owner_id`。
- 用户确认账户删除后，系统 SHALL 先撤销会话、拒绝新的操作、删除该 owner 的 thread，并通过 LangGraph 公共 `delete_thread(thread_id)` 清理 checkpoint，最后删除用户和所有者记录。数据库级联不替代 checkpoint 清理。
- 删除、认领、升级清理和失败恢复 SHALL 可重试、可审计且不得留下可访问的孤儿 thread 或 checkpoint。

## 5. HTTP 与前端体验

- API SHALL 提供注册、登录、退出、当前身份、匿名认领和账户删除所需的最小端点；路由使用稳定错误 code、Pydantic 请求/响应模型和适当的 401、403、404、409、503 语义。
- Vue SHALL 提供可操作的登录、注册、匿名切换、当前身份、登出、匿名对话认领和账户删除体验；不得以“后端端点已存在”代替用户界面。
- 匿名进入工作区 SHALL 始终可达，认证界面不得像 AGI-saber 一样以未登录状态阻断整个应用。
- 账户入口 SHALL 常驻现有左侧会话栏：匿名状态显示登录和注册操作；登录状态显示当前用户名、匿名对话认领、登出和账户删除操作。账户操作不得挤压会话列表的最小可用空间。
- 窄屏下账户入口 SHALL 随现有可访问会话抽屉显示；打开、关闭、Escape 和焦点恢复沿用该抽屉的既有无障碍行为。
- 登录与注册表单 SHALL 提供用户名、密码、提交中状态、字段/凭据错误、重复注册错误、失效会话恢复及键盘可达行为；密码不得在提交成功后保留在页面状态。
- 已登录状态 SHALL 显示当前用户名、登出入口和账户操作入口。存在当前浏览器的可认领匿名对话时，界面 SHALL 显示明确的认领说明、确认操作、成功结果和失败反馈。
- 账户删除 SHALL 使用二次确认对话框，明确立即删除账户、会话、对话与 checkpoint 的不可恢复后果；删除中禁用重复提交，完成后回到匿名状态。
- 当用户尝试创建账号而 PostgreSQL 未配置、不可用或 schema 不可用时，Vue SHALL 显示弹窗，明确说明 PostgreSQL 当前不可用、用户模块不可用且账号不会被创建；不得仅显示通用网络错误或伪装为成功。
- 前端 SHALL 不把所有权、会话有效性或授权结果当作本地真相；服务端响应始终是权威来源。

## 6. 安全与可观测性

- Cookie SHALL 使用安全属性；所有改变状态的 Cookie 认证请求 SHALL 有明确的 CSRF 防护契约。
- 配置缺少安全会话所需秘密或秘密不合法时，启动/相关能力 SHALL fail closed；错误、健康信息和日志不得泄露秘密、Cookie、密码哈希或数据库底层异常。
- 审计/日志 SHALL 记录稳定的 owner、thread、删除与认领结果标识，避免记录凭据、用户消息或密码。

## 7. 降级策略

PostgreSQL 未配置、不可用或 schema 不可用时，现有 M03 SHALL 继续进入 memory degraded 模式。M04 SHALL 允许进程内匿名聊天继续可用，但注册、登录、匿名认领和账户删除 SHALL 返回稳定的身份基础设施不可用语义。匿名所有者及其后端上下文仅在当前进程有效，重启后失效；前端 SHALL 明确显示该限制。创建账号操作还 SHALL 显示 PostgreSQL 当前不可用、用户模块不可用且账号未创建的弹窗。

## 8. 最小目录增量

以下是 M04 的目录与职责边界。它记录已批准的最小实现表面，不要求在 Shape 中预建空文件，也不为未来模块预留层级。

```text
venagent/
  ownership/                         # 新增：M04 业务用例与消费方端口
    models.py                         # owner、用户、会话和结果值对象
    ports.py                          # ownership store、密码/会话能力的消费方契约
    service.py                        # 注册、登录、当前 owner、认领与删号编排
    errors.py                         # 稳定的 M04 业务错误
  conversation/                       # 扩展：每个 thread 操作接收并校验 owner_id
  infra/
    config/                           # 扩展：认证 Cookie/秘密配置与 fail-closed 校验
    platform/                         # 扩展：M04 migration、PostgreSQL 与内存 ownership adapter
  interfaces/http/
    ownership.py                      # 新增：HTTP schema、Cookie 映射与路由注册；不含业务事实
    routes.py                          # 扩展：组合 conversation 与 ownership 的薄路由
  bootstrap.py                         # 扩展：唯一 composition root 注入 ownership service

web/src/
  modules/
    ownership/                         # 新增：账户状态、左侧账户面板、登录/注册和删号弹窗
    chat/                              # 扩展：组合账户面板与既有聊天工作区

tests/
  test_ownership.py                    # 新增：用例、隔离、认领、删号和降级
  test_ownership_api.py                # 新增：Cookie、HTTP 错误与端点边界

web/tests/e2e/
  ownership.spec.ts                    # 新增：侧栏账户 UI、弹窗、降级、认领和删号主路径
```

- `ownership/` 是 M04 自己的 feature 模块；它不建立供 M05+ 预先复用的全局身份或授权平台。
- `conversation/` 只接收不透明 `owner_id` 并经其 store 过滤数据；它不得依赖 Cookie、密码哈希或 HTTP adapter。
- `infra/platform/` 只实现端口和数据库 migration，不承载注册、认领或删号业务决策。
- `interfaces/http/ownership.py` 只处理 Pydantic 边界、Cookie 与 HTTP 映射；授权和生命周期事实在 `ownership/` 与 `conversation/`。
- `web/src/modules/ownership/` 只服务已批准的左侧账户体验；不新建管理后台、组织页、角色页、SSO 配置页或未来用户资料页。

## 9. 验收

- 用户、访客和跨 owner 的对话/运行/导入/删除访问均由离线单元与 API 集成测试覆盖；跨 owner 操作不得泄露资源存在性或数据。
- 覆盖 Cookie 不透明性、密码不落盘、登录失败、会话到期/撤销、匿名认领、升级删除无 owner 数据、账户立即删除及 checkpoint 清理。
- 使用临时隔离数据库验证 schema、外键、索引、迁移和失败恢复；不得依赖真实凭据或网络。
- 浏览器自动化 SHALL 覆盖匿名进入、登录、注册、登出、加载、失败、无权、失效会话、降级、认领和删除状态；降级模式下创建账号必须显示所需弹窗，并保持现有聊天、SSE、取消和持久化回归通过。
