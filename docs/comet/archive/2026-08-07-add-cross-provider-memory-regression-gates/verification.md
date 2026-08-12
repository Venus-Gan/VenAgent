# Acceptance evidence

<!-- comet-native:acceptance-evidence:start -->
[
  {
    "acceptance_id": "acceptance-10bd3258b232ee3f689aa20c0ef40349c0b4629cad0fee2a2044fd36d2aa7049",
    "evidence_refs": [],
    "skipped_reason": "本 change 只有拟议完整规格；canonical 项目产物由 Archive 事务落地，归档前没有可合法引用的 Native 外证据文件。"
  },
  {
    "acceptance_id": "acceptance-263fa3630c6cc754d391a4ddedcdd965b9a5c6f06d1ef4f6c7e5e3374102e83c",
    "evidence_refs": [],
    "skipped_reason": "本 change 只有拟议完整规格；canonical 项目产物由 Archive 事务落地，归档前没有可合法引用的 Native 外证据文件。"
  },
  {
    "acceptance_id": "acceptance-767806d26b0ceb87ed77b327a44ba8b6e256f53221aa4216f7573c1ea44ff364",
    "evidence_refs": [],
    "skipped_reason": "本 change 只有拟议完整规格；canonical 项目产物由 Archive 事务落地，归档前没有可合法引用的 Native 外证据文件。"
  },
  {
    "acceptance_id": "acceptance-b8642a9f1f12a09bca1fb3ac51a432daf1282a3e19774557ed9af02f4bed8ac6",
    "evidence_refs": [],
    "skipped_reason": "本 change 只有拟议完整规格；canonical 项目产物由 Archive 事务落地，归档前没有可合法引用的 Native 外证据文件。"
  }
]
<!-- comet-native:acceptance-evidence:end -->

# Commands and results

- `Compare-Object` 对比 canonical 与拟议完整规格：canonical 79 行，拟议 83 行，新增 4 行（其中一行为段落分隔空行），删除 0 行；新增正文仅为 M06/M07 共存、M08 隔离和全局跨 provider 验证条款。
- `rg -n "M05 共存回归|M05 隔离回归|新增 ContextProjection provider|改变 M05 来源资格|evidence 提升" ...`：命中 brief 与拟议规格中的全部三组责任和语义变更边界。
- `git diff --check -- docs/comet/changes/add-cross-provider-memory-regression-gates/brief.md docs/comet/changes/add-cross-provider-memory-regression-gates/specs/refactor-roadmap/spec.md`：退出码 0，无空白错误。
- `comet native check add-cross-provider-memory-regression-gates --json`：receipt `runtime/evidence/check-receipts/50d1bd8d64ae319b1570a5bbc7eea0c6cdce4a2f47975435601ebdae514c1929.json`，状态 passed；本 change 使用 no-code scope，选择和扫描文件数均为 0，因此该 receipt 只证明 scope 与检查状态新鲜，不作为 Markdown 内容扫描证据。

# Skipped checks

- 未运行 pytest、Ruff、compileall、Vue build、浏览器或 PostgreSQL 测试：本 change 只修订路线完整目标规格，不修改运行时代码、配置、数据库、API、前端或测试。
- acceptance evidence 未引用 change 内拟议规格：Native 将 workflow 路径排除为敏感证据，canonical 项目产物只能由 Archive 事务落地；因此四项均记录归档前无合法 Native 外证据文件。
- 未运行 Markdown 专用 linter：项目未配置该原生门槛；使用定向内容核对、完整规格对比和 `git diff --check` 验证文本。

# Spec consistency

- M06/M07 条款保持工具与任务图所有权不变，只把 M05 共存回归明确归给引入该能力的 change。
- M08 条款保持 evidence 与个人记忆的事实、关系、权限和删除边界，新增双 provider 隔离验证及 evidence 提升时必须修订 M05 的要求。
- 全局规则区分并列 provider 的针对性共存回归与改变既有模块语义时的 canonical spec 修订和扩大评测，没有要求为回归另建形式性 change。
- 原路线顺序、ContextProjection 演进、模块 intake、其他发布要求和非目标完整保留，未创建未来 capability、provider、目录或空实现。

# Known limitations and risks

- 本 change 只规定未来 change 的验证责任，不提前冻结工具结果 `source_ref`、evidence 提升协议、预算数值或具体测试数据；这些仍须在 M06/M07、M08 各自 Shape 中依据真实接口决定。
- 当前没有 M06/M07 或 M08 运行时实现，因此本报告不能提供跨 provider 运行证据；路线条款要求相应能力实现时补齐该证据。

# Conclusion

PASS。四个验收项均由拟议 `refactor-roadmap` 完整规格直接覆盖；规格对比确认没有删除既有规划，定向检索和空白检查通过，跳过项与 no-code receipt 的证据边界已如实记录。
