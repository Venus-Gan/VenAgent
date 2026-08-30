# ADR-0010：src 包布局（venagent/ → src/，web/ 归位 src/web/）

- 状态：已采纳（2026-08-30 用户拍板，形态 C）
- 关联：ADR-0002（目录树与文件归位）、`docs/wayfinder/assets/目录平整与提交-计划.md`（实施计划）、`docs/wayfinder/assets/新目录树-draft.md`（定稿树）

## 背景与动因

用户要求整理目录（消去 `venagent/` 目录印象）并准备 split commit。曾讨论两种形态：

- **形态 A（根级多包）**：17 个子包上提为根级包，真正取消 `venagent/` 目录。调查发现三重硬风险：
  1. 根级 `platform/`、`mcp/` 会遮蔽 stdlib `platform` 与 PyPI mcp SDK（`.venv` 内 100+ 处 `import platform`、google-genai/anthropic 的 `from mcp import ...` 全部被劫持）；
  2. 包内 264 处跨子包相对导入（`from ..`/`from ...`）全部失效，须改绝对导入；
  3. tests 336 处 `from venagent.*` 改写。
- **形态 C（src 包，本次采纳）**：`git mv venagent src` + `git mv web src/web` + import 前缀替换（`venagent.` → `src.`）。import 名带 `src.` 前缀 → site-packages 解析不受影响，遮蔽风险消除；包内相对导入零改动；入口 `python -m src` 保留。

## 决策

1. **`venagent/` 包改名 `src/`**（包级改名，`src/__init__.py`、`src/__main__.py`、`src/bootstrap.py` 就位）；**`web/` 移入 `src/web/`**（无 `__init__.py` → setuptools 不收录、不进 wheel）。
2. **src 必须是包，不得退化为目录容器**：禁止用 `pythonpath=["src"]` + `import agent`——那会重新引入 platform/mcp 遮蔽。任何新工具/脚本沿用 `import src.xxx`。
3. **产品标识保留，不随改名**：数据库表 `venagent_schema_migrations`、DB 库名/用户 `venagent`、JWT issuer/audience `venagent`/`venagent-web`、logger 名 `venagent.*`、cookie 名 `venagent_*`、docker label/容器名 `venagent-*`、容器内路径 `/workspace/.venagent/skills`、skills `compatible_runtimes=("venagent",)`、github UA、`venagent-state.lock`、localStorage 键/事件名 `venagent-*`、pyproject `name = "venagent"`（**pip 包名与 import 名可以不同**）。替换纪律：`venagent` → `src` 只作用于 import 语句与 ADR 列出的少数字符串，禁止盲替换。
4. **mcp-configs 运行时目录包锚定**：`bootstrap.py:121` `DEFAULT_MCP_CONFIG_PATH` 由 `Path.cwd() / "mcp" / ...` 改为 `Path(__file__).resolve().parent / "mcp" / "mcp-configs" / "mcp-servers.json"`——删除唯一 cwd 敏感依赖，生成物落 `src/mcp/mcp-configs/`（gitignored；无 `__init__.py` 不进 wheel）。派生链（McpConfigStore + ensure_defaults / `state/` approvals·operations·artifacts·invocations·run-tool-snapshots·skills / `venagent-state.lock`）自动跟随。
5. **入口**：`python -m src`；`__main__.py:40` prog、`:65` uvicorn 字符串同步 `src.*`。
6. **已知边界（不扩 scope）**：
   - 包锚定在非 editable 安装（site-packages）时不可写；项目属「仓库内运行」范式，接受并文档化。
   - `config/loader.py:147` 与 `interfaces/http/routes/settings.py:234` 的 config.yaml 定位仍为 cwd 锚定，与 mcp-configs 包锚定不一致——暂不统一，另议。
7. **回退**：改名为纯机械操作，`git revert` 整体恢复。

## 后果

- 全仓库 import 前缀替换（tests 约 336 处 + evals 2 处 + __main__ 2 处 + pyproject 3 处 + .gitignore 路径）；
- 目录树定稿（`新目录树-draft.md`、README、`tests/test_package_layout.py` 引用关系随 src 更新，但 tests 面貌不变）；
- 改名后须重跑 `pip install -e ".[dev]"`（旧 editable 索引 venagent* 失效）。
