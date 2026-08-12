# VenAgent 代码编写 Prompt 路由完整目标规格

## 1. 目标和阶段边界

VenAgent SHALL 在 Comet Native 的 Shape 已批准后、实际开始 Build 代码时，使用本机 ECC prompts 及其 rule packs 作为可复核的实现和验证配方。它们不创建独立生命周期，也不得替代 Comet Native 的 Shape、Build、Verify 或 Archive。

`ecc-feature-dev` SHALL 是新功能、缺陷修复和实质性重构的 Build 入口。它的代码探索、现有实现优先、集成点检查、实现与质量复核只可在已批准的 Shape 范围内执行；它不得重开需求澄清、绕过阶段边界或改变已确认的产品决定。

纯说明文档、格式调整或不影响行为的元数据修改不触发本路由。实现者应按实际变更选择最小必要的专项 prompts，并在 Verify 中记录实际使用、不可用项与等价降级。

## 2. Python 实现基线

凡修改 VenAgent 的 `.py` 或 `.pyi` 文件，Build SHALL 应用 `ecc-rules-pack-common` 与 `ecc-rules-pack-python`。Python 规则覆盖 common 规则中的编码风格、开发流程、性能、安全和测试要求；Python 专项规则覆盖 PEP 8、公共函数类型标注、Ruff 格式化与 lint、资源上下文管理、pytest、Bandit 及 Pythonic pattern。

实现 SHALL：

- 使用清晰命名、聚焦函数、显式错误处理和边界输入验证；不得静默吞掉异常、硬编码秘密或为未来需求预建抽象。
- 优先使用不可变值对象或受控状态更新；在异步、并发和持久化路径中明确资源所有权、取消与失败语义。
- 保持业务用例不依赖具体 adapter，`repo/` 只实现 feature ports，`platform/` 只拥有共享技术资源，`bootstrap.py` 是唯一 adapter 装配点，`interfaces/http/` 不承载业务事实；活动实现不得重新引入 catch-all `infra/`。
- 新增或变更行为时使用现有 pytest 约定覆盖正常、失败、边界和隔离行为；测试范围由风险和变更范围决定，不把全仓覆盖率作为硬门槛。

## 3. 按变更类型追加的 prompts

| 变更 | 必须使用的执行配方 | 最低结果 |
|---|---|---|
| 任意运行时代码 | `ecc-feature-dev`、`ecc-code-review` | 确认范围、阅读相关现有实现、运行由 Comet Verify 选择的项目原生测试，完成通用正确性/安全/可维护性复核 |
| Python 代码 | 上述配方加 `ecc-rules-pack-common`、`ecc-rules-pack-python`、`ecc-python-review` | 检查类型、异常、资源、格式/lint 可用性、Python 安全风险与相关 pytest |
| FastAPI HTTP 表面 | Python 配方加 `ecc-fastapi-review` | 检查 router 薄层、Pydantic 输入/输出模型、依赖注入、异步 I/O、异常、CORS/认证/日志及测试 override |
| 身份、授权、MCP、命令执行、文件、凭据、外部网络或高风险数据操作 | 相应配方加 `ecc-security-scan` | 检查最小权限、输入/输出边界、秘密保护、注入/SSRF/路径风险、授权与审计测试 |
| 仅删除或收敛死代码 | `ecc-refactor-clean` 加相关测试 | 逐项确认引用和动态入口，删除前后运行相关测试；不与功能重构混合 |

## 4. 可用性与降级

执行者 SHALL 先确认 prompt、所需 rules、项目原生格式器/静态检查器和测试命令是否可用。若某个 ECC prompt 或其原生 agent 无法直接调用，执行者 SHALL 在主会话依据该 prompt 的公开检查项完成等价检查，并在 Verify 中记录：实际可用性、命令、结果、跳过理由和剩余风险。

执行者 SHALL NOT 将未安装的 `ruff`、`mypy`、`bandit` 或安全扫描器写为已通过；也不得为使用外部 prompt 而安装、复制或重复维护另一份 ECC，除非有独立批准的依赖或工具链变更。

## 5. 前端和 Agent 专项

改动 `web/` 的 Vue 3 + TypeScript 代码时，Build SHALL 在上述通用代码审查之外使用当前模块路由指定的前端能力，并验证加载、失败、降级、无权和响应式状态。它不适用 Python rule pack。

改动 LangChain 或 LangGraph 运行时前，Build SHALL 先遵循模块路由指定的 LangChain/LangGraph 技术能力与官方资料；涉及图节点、state、工具、持久化或 interrupt 时必须使用对应的专项规则。该专项要求补充而不替代本规格中的测试、审查和安全门槛。
