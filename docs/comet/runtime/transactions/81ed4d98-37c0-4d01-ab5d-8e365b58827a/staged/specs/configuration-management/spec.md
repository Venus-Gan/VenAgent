# 运行时配置管理完整目标规格

## 1. 目标与配置来源

VenAgent SHALL 使用一个不可变、严格校验的应用配置对象作为 CLI、FastAPI、LLM adapter 与持久化 runtime 的唯一配置来源。配置合并顺序 SHALL 为：内建安全默认值 < `config/config.yaml` < `config/config.local.yaml` < 被忽略的根目录 `.env` < 显式进程环境变量。

`config/config.yaml` SHALL 被版本控制，并只保存可安全共享的结构化默认值。`config/config.local.yaml` SHALL 被 Git 忽略，并只保存本机的非敏感覆盖。两者均 SHALL NOT 含 API key、密码、token、私钥或完整数据库连接串。

配置模块 SHALL 只加载一次根目录 `.env`，且不得覆盖同名显式进程环境变量。启动路径不得再次单独解析 `.env`。

## 2. 配置模型与安全边界

配置模型 SHALL 至少定义 `llm`、`server` 与 `persistence` 三个严格 section，拒绝 YAML 中的未知 section 或字段、错误类型和不合法的嵌套结构。

- `llm` SHALL 保存非敏感的 provider、model、API mode、URL、Azure 标识及类型化请求参数。
- `server` SHALL 保存端口等非敏感 HTTP 服务参数。
- `persistence` SHALL 表示持久化运行时配置；其完整 `database_url` 为秘密字段，只可从环境注入。

错误、日志、配置诊断和测试输出 SHALL 仅显示字段路径和稳定原因，不得显示秘密原值。需要显示配置时 SHALL 使用脱敏副本。

## 3. 环境覆盖

应用 SHALL 仅接受白名单中的嵌套环境覆盖键；例如 `VENAGENT_LLM__MODEL`、`VENAGENT_LLM__API_KEY`、`VENAGENT_SERVER__PORT` 与 `VENAGENT_PERSISTENCE__DATABASE_URL`。覆盖键的双下划线表示配置路径，值 SHALL 在合并前按目标字段类型解析。

未知的 `VENAGENT_<SECTION>__<FIELD>` 覆盖键 SHALL 使启动失败；无双下划线的其他运行环境变量不属于配置层。`.env` 与显式进程环境均使用相同的白名单和解析规则。

`VENAGENT_CONFIG_PATH` MAY 显式选择共享 YAML 配置文件；该路径不存在、不可读或不是 YAML mapping 时 SHALL 失败。未指定时 SHALL 使用仓库根的 `config/config.yaml`。本地覆盖路径固定为同目录 `config.local.yaml`。

## 4. 迁移与兼容性

旧 `LLM_*` 与 `VENAGENT_DATABASE_URL` 变量 SHALL 不再构成配置来源。若启动时检测到任何非空旧变量，应用 SHALL 失败并指出对应的 `VENAGENT_<SECTION>__<FIELD>` 迁移方向，但不得回显原值。

全空的新 LLM 配置 SHALL 保持现有无网络本地回复模型。任一新的 LLM 配置字段存在时 SHALL 触发真实模型配置的完整严格校验；部分配置不得静默回退到离线模型。

未设置 `VENAGENT_PERSISTENCE__DATABASE_URL` 时，应用 SHALL 保持现有进程内持久化降级模式及健康检查契约。

## 5. 文档与验收

- `config/config.yaml`、`config/config.local.yaml.example`、`.env.example`、README 和 Compose SHALL 清晰区分共享设置、开发机非敏感覆盖、秘密注入和 Compose 自身秘密。
- `.env.example` SHALL 仅列出秘密或部署环境覆盖示例，不重复承载结构化默认配置。
- 测试 SHALL 覆盖层级优先级、深度合并、未知字段/覆盖键、类型解析、秘密脱敏、旧变量拒绝、离线模型和持久化降级。
