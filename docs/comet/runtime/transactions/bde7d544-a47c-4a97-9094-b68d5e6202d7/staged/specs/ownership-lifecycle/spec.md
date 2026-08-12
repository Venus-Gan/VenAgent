# Ownership Lifecycle 完整目标规格

## 1. 目标

VenAgent SHALL 保持 guest、account user 与 temporary guest 的 owner-scoped 身份体系，并为后台 AgentRun 增加最小、可撤销、绑定单 run 的 `RunGrant`。worker 以服务身份领取任务，但不得代行 owner 或继承发起 session 的完整权限。

## 2. 既有身份基线

- durable 模式支持 guest 与 account user；temporary 模式只支持 temporary guest。owner、user、session、refresh、密码与 JWT 的安全边界保持独立于 conversation/run。
- access token 解析后 SHALL 回查 session active、owner active、owner/session identity 一致；不存在与错误密码保持抗枚举响应，refresh 轮换与短宽限保持并发安全。
- 所有 conversation、message、run、grant、cancel、retry、stream 和 approval 查询按 owner 授权；不存在资源与跨 owner 访问返回等价安全错误。
- Origin/CORS、HttpOnly refresh Cookie、短期 access token、密码哈希、速率限制、日志脱敏和身份多标签页失效通知继续适用。

## 3. RunGrant

RunGrant 至少表达：

```text
grant_id
run_id
owner_id
tenant_id
conversation_id
allowed_data_scopes
allowed_action_classes
authorization_epoch
requested_by_session_id
expires_at
revoked_at
```

- 初次 user message/run 创建事务 SHALL 同时签发 RunGrant 并关联 run；retry 创建新的 run 与 grant，不复用旧 grant。
- grant 只允许当前 conversation、当前 run artifact namespace，以及后续被 M05/M08 明确过滤/引用的数据范围；本 change 的 action class 仅覆盖完成基础模型运行所需最小动作。
- grant 只能向后续 M06 请求更窄的 operation authorization，不能直接授权任意工具、命令、文件、网络、凭据或 owner 全部资源。
- `requested_by_session_id` 只用于归因审计，不是恢复凭据。JWT、refresh、Cookie、API key、credential handle 和明文秘密不得进入 grant、run、State、checkpoint 或 Prompt。
- worker 恢复时验证 run/owner/tenant/conversation 绑定、授权 epoch、expiry、revocation 和资源生命周期，再派生进程内 `ExecutionAuthorization`。

## 4. Session 与授权生命周期

- 普通 logout、access token 过期或发起 session 撤销默认不取消已创建且 RunGrant 仍有效的后台 run；新客户端能否查询该 run仍由当前 owner身份决定。
- owner deleting/deleted、安全撤销、tenant 失效或 authorization epoch 变化 SHALL 立即使旧 grant不可用，并触发 run 取消/安全收敛。
- guest grant 有效期不得超过 guest owner/conversation 生命周期；guest 过期、conversation 删除、run 终态或显式 grant 撤销后不得继续使用。
- 改密撤销其他 session 不自动撤销同 owner 的既有 grant，除非安全策略同时递增 authorization epoch；该选择必须有稳定审计 reason。
- 登录/注册导致浏览器切换 owner 时，旧 owner run可按原 grant继续，但新 owner界面不得读取或控制它。

## 5. 执行权限边界

- 所有需要 owner 数据的 application port SHALL 接收显式 `ExecutionAuthorization`，不得只凭 owner ID 给予全量访问。
- ContextProjection 只接收脱敏 `IdentityView`、可用能力和策略结果，不接收 grant 结构、session、credential handle 或权限秘密。
- 后续工具操作的有效权限是 RunGrant 上限、owner 当前权限、M06 工具策略、sandbox 策略与 ApprovalItem 的交集；Prompt 与审批都不能扩大 grant 上限。
- 缺少或不匹配授权时 fail closed，并使用安全稳定 reason；不得在日志、SSE 或 API 回显策略内部细节。

## 6. Owner 删除与匿名回收

- account 删除先验证用户与显式确认，原子把 owner 标记 deleting、撤销 session/epoch 并使全部资源不可访问，再异步取消/对账 run 和删除 conversation/message/grant/checkpoint。
- 删除可重复、可恢复；中途失败保持 deleting，不能重新登录或访问部分数据。完成后创建全新 guest 身份。
- guest TTL 与回收只由明确业务成功/生命周期规则推进；active/waiting run 和删除竞态必须通过数据库锁/CAS 处理。
- temporary owner与数据随进程结束消失，不迁移为 durable owner。

## 7. HTTP 与前端

- 身份 bootstrap 在渲染 owner 数据前完成；身份转换通过统一入口清理旧 owner conversation/run/partial 观察。
- 登录/注册明确匿名历史不迁移；temporary 账号入口显示统一不可用对话框，不发起伪请求。
- logout 不向后端逐个取消既有 run；前端停止旧 owner观察并清理其本地缓存。owner 删除属于安全取消路径。
- 401 最多执行 single-flight refresh 后重试安全、幂等请求；run 创建结果不确定时先使用 client request ID/query 对账，不盲目重复。

## 8. 验收

- 覆盖 guest/user/temporary guest bootstrap、token/session/owner 回查、refresh 轮换宽限、撤销、过期、Origin/CORS 与抗枚举。
- 证明跨 owner conversation/message/run/query/stream/cancel/retry/approval 不泄露存在性。
- 证明普通 logout/session 过期不自动取消有效 run，而 owner 删除、安全 epoch 变化、guest/tenant 失效会阻止恢复并安全收敛。
- 证明 worker 仅凭有效 RunGrant/ExecutionAuthorization访问最小范围，秘密不进入持久对象、Prompt、SSE 或日志。
- 覆盖删除中断恢复、活动 run 竞态、孤儿 guest 清理和跨标签页身份切换。
