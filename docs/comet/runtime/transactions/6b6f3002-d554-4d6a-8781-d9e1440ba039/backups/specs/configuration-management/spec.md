# 运行时配置管理完整目标规格

## 1. 配置来源与位置

VenAgent SHALL 使用不可变、严格校验的应用配置对象作为 CLI、FastAPI、LLM adapter 与持久化 runtime 的唯一配置来源。配置合并顺序 SHALL 为：内建默认值 < `venagent/config/config.yaml` < `venagent/config/config.local.yaml` < 被忽略的仓库根 `.env` < 显式进程环境变量。

`venagent/config/config.yaml` SHALL 随 Python 包分发并保存可安全共享的结构化默认值。`venagent/config/config.local.yaml` SHALL 被 Git 忽略，并只保存本机的非敏感覆盖。两者均 SHALL NOT 含 API key、密码、token、私钥或完整数据库连接串。

配置模块 SHALL 只加载一次根目录 `.env`，且不得覆盖同名显式进程环境变量。启动路径不得再次单独解析 `.env`。

## 2. 配置模型与安全边界

配置模型 SHALL 至少定义 `llm`、`server` 与 `persistence` 三个严格 section，拒绝 YAML 中的未知 section 或字段、错误类型和不合法的嵌套结构。

- `llm` SHALL 保存非敏感的 provider、model、API mode、URL、Azure 标识及类型化请求参数；API key 仅从 `LLM_API_KEY` 注入。
- `server` SHALL 保存端口等非敏感 HTTP 服务参数。
- `persistence` SHALL 保存 `enabled`、`host`、`port`、`database` 与 `user`。其 `password` 仅可由 `POSTGRES_PASSWORD` 注入。

当 `persistence.enabled` 为真且密码非空时，配置对象 SHALL 从这些字段组装 PostgreSQL 连接串，并对用户名、密码和数据库名进行 URL 编码。错误、日志、配置诊断和测试输出 SHALL 仅显示字段路径和稳定原因，不得显示秘密原值。

## 3. 环境覆盖

应用 SHALL 只接受白名单环境输入：`LLM_*` 为 LLM 字段，`POSTGRES_PASSWORD` 为持久化密码，`VENAGENT_SERVER__PORT` 为服务端口。未知的 `VENAGENT_<SECTION>__<FIELD>` 覆盖键 SHALL 使启动失败。

`VENAGENT_CONFIG_PATH` MAY 显式选择共享 YAML 配置文件；该路径不存在、不可读或不是 YAML mapping 时 SHALL 失败。未指定时 SHALL 使用包内 `venagent/config/config.yaml`，本地覆盖路径固定为同目录 `config.local.yaml`。

## 4. 持久化与降级

默认共享 YAML SHALL 启用本机 `127.0.0.1:5432` 的 `venagent` PostgreSQL 服务及用户名 `venagent`。未设置 `POSTGRES_PASSWORD`、数据库连接失败或 schema 不可用时，应用 SHALL 保持现有进程内持久化降级模式及健康检查契约。

数据库 schema 仍只能通过 `python -m venagent migrate` 显式创建或升级；普通启动不得静默执行 DDL。

## 5. 前端开发代理

默认 `server.port` 为 `8090` 时，`web/vite.config.ts` SHALL 将 `/api` 与 `/health` 代理到 `http://127.0.0.1:8090`，使默认的前后端开发命令无需临时端口覆盖即可联通。

## 6. 文档与验收

- `venagent/config/config.yaml`、本地覆盖示例、`.env.example`、README 与 Compose SHALL 清晰区分共享基础设施参数、本机非敏感覆盖、密码注入与 Compose 自身秘密。
- `.env.example` SHALL 列出 LLM API key 与 `POSTGRES_PASSWORD`，不得要求完整数据库连接串。
- 测试 SHALL 覆盖层级优先级、YAML 秘密拒绝、密码注入、连接串编码、无密码降级与包内默认 YAML 的定位。
