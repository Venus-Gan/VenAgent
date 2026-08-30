# ADR-0002: 新目录树与文件归位

目录树以 `docs/wayfinder/assets/新目录树-draft.md` 定稿 v1.0 为唯一依据（README 同步改写）。归位原则：一外部系统一文件、一槽位一 source、一领域对象一 repo；正面粒度参考 final/，负面教训是其 agent.py 1166 行 / memory.py 993 行的巨型文件。

关键收敛：tools 19→15（exec_command→executor、schema→models、policy/state_directory→control）；memory 24→15（authorization→recall、capabilities/command_adapter→management、job_worker→jobs、graph→graph_memory/service、long_term/extractor→model_adapters、conflict/policy→facts；MemoryCapabilityRegistry 被 bootstrap 引用须同步 import）；config 弃 .env 拆 `models.py` + `loader.py`（AppConfig 定义独立）；tests 按 `tests/<module>/` 镜像，M06 重写测试归 tests/agent/。

M08（`rag/`、`document/`、`platform/milvus|es`）与 M07（`agent/planning/`、`promptctx/source_planner.py`）只文档留位，不空建目录。

来源：Wayfinder 票 `目录结构梳理定稿`（resolved）。
