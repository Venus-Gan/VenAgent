---
wayfinder: ticket
id: repo-mirror
title: repo 双镜像去留（temporary/postgresql 平行实现）
labels: [wayfinder:grilling]
blocked_by: []
status: resolved
claimed_by: captain
resolved_comment: 方向锁定 (a) 删除 temporary 树 + (b) 收敛版会话路径：删 memory 临时镜像、会话路径收敛为单一内存 driver；JWT 与 PG 解耦独立降级；owner=None 放行统一为 PG 严格语义。经 grilling 两轮（含 repo 双镜像只读调查子代理报告）用户逐项拍板，见 Resolution。map Decisions so far 已更新。
---

## Question

`repo/` 现有 durable/temporary 双镜像（29 文件 / 5430 行；postgresql runs 785 / long_term 699 / ownership 413 / jobs 343，temporary runs 597 / long_term 421 / ownership 271 / jobs 247，内存字典平行实现）。去留三选：
- (a) **删除镜像**：单 repo 层 + `ErrUnavailable`/degraded 显式降级（AGI-saber 模式；无 PG 时持久功能显式不可用，非降级为内存）；
- (b) 保留但收敛为单个 `backend=memory` driver（保「无 PG 本地可全功能跑」体验）；
- (c) 挂进 `目录结构梳理定稿` 再定。
推荐 (a)：用户确认「为低耦合而低耦合」是病；临时镜像是 repo 里最大重复源；AGI-saber 证明无镜像也能清晰降级（persistence repos db==nil→ErrUnavailable；平台 Connect→(nil,"disconnected")；Docker 不可用→MockSandbox）。**代价：本地无 PG 时持久功能不可用（靠 docker compose 起 PG）——这是产品决策而非技术决策。**

## Context

README 目录树把 temporary/ 记为正式树的一部分——本票结论将改变该树，与 `目录结构梳理定稿` 联动。依赖边界（README）：`repo/` 只实现 ports，`platform/` 只管技术资源，PG feature adapters 用 `platform/postgresql/runtime.py` 同步业务连接池，不自行读 DSN/建池。final/repo 也是单层 8 文件、无 temporary。AGI-saber 降级模式＝「标记+上层决策」而非内存字典镜像。

**只读调查子代理报告（2025 关键新事实）**：
1. temporary 不是 PG 的真镜像，而是「被内建关闭的降级实现」：自带 durable 旗标体系（`temporary/memory/state.py:33-34`、`temporary/ownership.py:44-53`），但 bootstrap 装配恒传 `durable=False`（`bootstrap.py:453-473`），long-term 能力被恒关——「平行实现」定位自相矛盾。
2. **JWT 矛盾点**：`bootstrap.py:159-164`——PG 已连通（mode=durable）时只要 `jwt_secret` 长度 <32 就 `persistence.close()` 强制改道 temporary，且状态显示 `postgresql="connected"` 与 `mode="temporary"` 自相矛盾。
3. **owner=None 放行是唯一可观察的安全语义差异**：temporary `authorize_run`（`temporary/runs.py:173-202`）在 owner 记录缺失时跳过 lifecycle/epoch 校验仅凭 grant 放行（owner 删除后 grant 仍在可绕过）；PG 用 INNER JOIN（`postgresql/runs.py:256-258`）→ `RunNotFound` 恒拒绝。
4. 上层显式降级骨架已存在：capability registry 标 `disabled`（`bootstrap.py:365-407`）、统一 503 `persistence_unavailable`（`interfaces/http/app.py:171-188`）、memory recall 失败转移能力状态（`memory/recall.py:91-112`）——删 temporary 是删掉镜像后自然落到既有路径，不是从零建。
5. 删 temporary 的连带约束：`test_package_layout.py:147-148` 断言 bootstrap 符号空间同时含两个 store；README 374-408 行把 temporary/ 记为正式树（非 legacy）；G1 graph mixin（`temporary/memory/graph.py`）仅测试接线（生产走 neo4j 树，`bootstrap.py:192` 恒显式传 graph_store）。
6. health 矛盾待决：`platform/runtime.py:67-71` 写死 `anonymous_chat: "available"`、`run_execution: "available"`——但删 temporary 后无 PG 时 conversation/run/ownership 没有 store 实现（bootstrap 装配点唯一）。

## Resolution

**RESOLVED**（经 grilling 两轮，用户逐项拍板「按你推荐」）：

1. **方向锁定 (a) 删除 temporary 树**：单 repo 层（postgresql + neo4j）+ 显式降级。临时镜像是最大重复源，且其 durable 旗标恒关，连「真镜像」都算不上。
2. **降级语义 = a1**：无 PG 时持久化调用以稳定异常 + 统一 503 `persistence_unavailable`（复用 `interfaces/http/app.py:171-188` 既有骨架）+ capability registry 标 disabled/unavailable（`bootstrap.py:365-407`）。不静默吞错。
3. **本地体验 = Q4 收敛版 (b)**：**删 memory 临时镜像（`temporary/memory/*` ≈ 1026 行：long_term/jobs/index/short_term/graph/fact_state/state/__init__）**；**会话路径（conversation/run/ownership/state ≈ 1167 行）收敛为单一内存 driver** 保留「无 PG 本地可跑匿名对话/工具执行」。无 PG 时 memory 持久能力（long-term/extraction/index/graph）显式 unavailable/disabled，落到既有 capability registry 路径。G1 graph mixin（`temporary/memory/graph.py`，仅测试接线）随删，测试改用 DisabledGraphMemoryStore/neo4j mock。
4. **JWT 与 PG 解耦**：删除 `bootstrap.py:159-164` 强制改道整段；JWT<32 只影响账号/身份能力（`authentication_configuration_unavailable`，reason_code 已存在），mode 恒为 durable 时对话照常持久，账号功能独立 unavailable。
5. **owner=None 放行统一为 PG 严格语义**：owner 缺失/非 active → 拒绝（temporary 侧删除 `temporary/runs.py:173-202` 的放行分支）；随树删除自然消除差异。
6. **连带更新**：`test_package_layout.py:147-148` 改为只断言 PG 树；README 374-408 行 temporary/ 段移除；health 中 `anonymous_chat`/`run_execution` 的「available」承诺按无 PG 时会话路径是否可用重新核对（会话路径保留 → 维持 available，但需在实现时确认装配成立）。

→ 已记入 map「Decisions so far」；具体删除清单、单内存 driver 的命名与装配点、README 目录树改写交 `目录结构梳理定稿`（new-directory-tree，本票已解除其一个阻塞项）。
