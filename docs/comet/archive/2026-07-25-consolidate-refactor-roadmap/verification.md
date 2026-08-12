# Acceptance evidence

<!-- comet-native:acceptance-evidence:start -->
[
  {
    "acceptance_id": "acceptance-1160607f47880713031c0ff71cba08a5ff68a9d70a901282845f5139a82f8f74",
    "evidence_refs": [],
    "skipped_reason": "此 change 的已允许部分 scope 只包含两项无关测试修改；路线和项目规则文件不属于 Runtime 可绑定的实现 scope。已通过记录在 Commands and results 的只读扫描人工核对。"
  },
  {
    "acceptance_id": "acceptance-41c0f356f6f8393c361004044c787edf70d7e5d2a737d7d6ac81d6d5c7948dff",
    "evidence_refs": [],
    "skipped_reason": "此 change 的已允许部分 scope 只包含两项无关测试修改；路线和项目规则文件不属于 Runtime 可绑定的实现 scope。已通过记录在 Commands and results 的只读扫描人工核对。"
  },
  {
    "acceptance_id": "acceptance-5441143157b6e19646757bd1d2c0dce224f75cdcc56904c064d48cd248b9de61",
    "evidence_refs": [],
    "skipped_reason": "此 change 的已允许部分 scope 只包含两项无关测试修改；路线和项目规则文件不属于 Runtime 可绑定的实现 scope。已通过记录在 Commands and results 的只读扫描人工核对。"
  },
  {
    "acceptance_id": "acceptance-642eeb949e1b3f962d653e7ef0d7ce364824061a32b607c949c27027a80ecae7",
    "evidence_refs": [],
    "skipped_reason": "此 change 的已允许部分 scope 只包含两项无关测试修改；路线和项目规则文件不属于 Runtime 可绑定的实现 scope。已通过记录在 Commands and results 的只读扫描人工核对。"
  },
  {
    "acceptance_id": "acceptance-c1ba1250b8d488272fc0ae2b5eadbda05fd459ec0fbaa3ee33b601cdb9d4756e",
    "evidence_refs": [],
    "skipped_reason": "此 change 的已允许部分 scope 只包含两项无关测试修改；路线和项目规则文件不属于 Runtime 可绑定的实现 scope。已通过记录在 Commands and results 的只读扫描人工核对。"
  },
  {
    "acceptance_id": "acceptance-d1e5e40799e20ea5a10f23326d599e5304ff0b3747ee7583a52d3b991ff6b851",
    "evidence_refs": [],
    "skipped_reason": "此 change 的已允许部分 scope 只包含两项无关测试修改；路线和项目规则文件不属于 Runtime 可绑定的实现 scope。已通过记录在 Commands and results 的只读扫描人工核对。"
  },
  {
    "acceptance_id": "acceptance-f24b448cbb201fd4c4313f97f79da19a5f62a519d47522fd027df4d20969e686",
    "evidence_refs": [],
    "skipped_reason": "此 change 的已允许部分 scope 只包含两项无关测试修改；路线和项目规则文件不属于 Runtime 可绑定的实现 scope。已通过记录在 Commands and results 的只读扫描人工核对。"
  }
]
<!-- comet-native:acceptance-evidence:end -->

# Commands and results

- `rg` checked canonical project rules, route specifications and module router for removed M05--M18 identifiers. No canonical old-route references remain.
- `git diff --check -- AGENTS.md docs/comet/specs .agents/skills/venagent-module-router` completed without whitespace errors.
- `git diff --stat -- AGENTS.md docs/comet/specs .agents/skills/venagent-module-router` confirmed the change is limited to route, router, adjacent specifications and project rules.

# Skipped checks

- Product test suites were not run because this change does not modify runtime or frontend implementation.
- `tests/test_config.py` and `tests/test_llm.py` are user-confirmed unattributed changes outside the partial verification scope. They are not evidence for this route change and are not represented as passing.

# Spec consistency

The canonical route now has M01--M03 complete and six post-persistence product domains: M04 ownership-lifecycle, M05 memory-system, M06 tool-execution with the minimal sandbox first, M07 agent-orchestration on M06's approved tool contract, M08 rag, and M09 platform-governance.

The router matrix, router skill, AGENTS.md and M01--M03 neighboring specifications use the same numbering. AGI-saber remains a Go behavior and risk reference; the ECC Python rules govern only the VenAgent implementation target. `product-capability` is a conditional directory-planning capability, not a pre-build directory template.

# Known limitations and risks

- This verification accepts a partial scope that excludes the two unrelated test-file modifications named above.
- The route deliberately does not select vector, graph, MCP or sandbox implementations. Those choices remain subject to each module's Shape and `search-first` research.

# Conclusion

Pass. The approved compact route, targeted AGI-saber intake rules, conditional ECC directory-planning trigger and M06-before-M07 sandbox dependency are consistently represented in the verified documentation scope.
