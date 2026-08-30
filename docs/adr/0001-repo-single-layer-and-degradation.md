# ADR-0001: repo 单层化与降级语义

删除了 `repo/temporary/` 镜像树，repo 层收敛为单一真相源：postgresql（Postgres 适配器）+ neo4j（图）+ inmemory（无 PG 时会话路径的内存驱动，仅 conversation/run/ownership/state，memory 无内存镜像）。双镜像曾造成一致性漂移与维护翻倍（一次记忆写入横跨两个树）。

降级语义：依赖缺失时由 capability registry 标记 `disabled`/`unavailable`，接口统一返回稳定异常并映射 503 `persistence_unavailable`，不静默吞错；`owner=None` 统一为 PG 严格语义（缺失/非 active 拒绝）。JWT<32 不再强制改道 temporary，只影响账号能力（`authentication_configuration_unavailable`）。

连带：`test_package_layout` 只断言 PG 树；README temporary 段移除。

来源：Wayfinder 票 `repo-双镜像去留`（resolved）。
