# Acceptance evidence

<!-- comet-native:acceptance-evidence:start -->
[
  {
    "acceptance_id": "acceptance-1805ebdbd0038bf1481be23e58f4c1abfc18b0c2eb29ab573279fde325d2fa88",
    "evidence_refs": [
      ".agents/skills/venagent-module-router/references/module-routing.md"
    ]
  },
  {
    "acceptance_id": "acceptance-58feda0f6139aab3131d7aa6ba3da884f6e235b042891fdd2509994a12e928d3",
    "evidence_refs": [
      ".agents/skills/venagent-module-router/SKILL.md",
      ".agents/skills/venagent-module-router/references/module-routing.md"
    ]
  },
  {
    "acceptance_id": "acceptance-63c547790eb415bbd587b6efb44ad48afe0ef5fb8253e0c35e73535c3effffad",
    "evidence_refs": [
      ".agents/skills/venagent-module-router/SKILL.md",
      ".agents/skills/venagent-module-router/references/module-routing.md",
      "AGENTS.md"
    ]
  },
  {
    "acceptance_id": "acceptance-dca9c4ab3615aafc06e218b438a734770a77f2e1495bc391e9276b4bc4db7001",
    "evidence_refs": [
      ".agents/skills/venagent-module-router/SKILL.md",
      ".agents/skills/venagent-module-router/references/module-routing.md"
    ]
  },
  {
    "acceptance_id": "acceptance-fb869462bbbc8083149caa83766fe05a0d9b584b43d24a1a0de73813cc510411",
    "evidence_refs": [
      ".agents/skills/venagent-module-router/SKILL.md",
      "AGENTS.md"
    ]
  }
]
<!-- comet-native:acceptance-evidence:end -->

# Commands and results

- PowerShell static validation confirmed the installed `search-first` file and all three project routing files exist; it also confirmed every M04--M18 identifier is present in the routing matrix and that the router links to that matrix. Result: pass.
- `rg -n "search-first|frontend-foundation|M04|M18|AGI-saber" AGENTS.md .agents/skills/venagent-module-router docs/comet/changes/skill-orchestration` confirmed the required governance, routing, frontend and legacy-reference statements. Result: pass.
- `git diff --check -- AGENTS.md .agents/skills/venagent-module-router docs/comet/changes/skill-orchestration` completed without whitespace errors. Result: pass.
- `comet native check skill-orchestration --json` returned `passed` with receipt `runtime/evidence/check-receipts/3a09849e3b973d1506849ede8044ebce0293c60784978785f0bf34f558b17547.json`.

# Skipped checks

- No Python unit, integration or browser test was run: this change adds governance and routing documentation only and intentionally does not modify VenAgent runtime code or the current Web UI.
- The built-in Native text checker selected zero files because the implementation scope is explicitly a no-runtime-code change and the affected project governance paths are ignored by Git. Its pass result is therefore not presented as content coverage.

# Spec consistency

- `AGENTS.md` names Comet Native as the only project lifecycle and defines the intake as a Shape input, not a parallel workflow.
- The router and M04--M18 matrix require common/Python/search-first intake, scope AGI-saber to named behavior topics, and explicitly state when no legacy comparison is required.
- The same three files declare the Vue 3 + TypeScript + Vite + Pinia + Vue Router baseline and require `frontend-foundation` to finish before M04 Build.
- The router points at the user-installed Codex `search-first` path and forbids fallback to temporary marketplace cache.

# Known limitations and risks

- The configured `search-first` path is host-specific (`D:\AITools\CodeX\skills\search-first\SKILL.md`). If the local Codex home changes or the skill is removed, a future module must stop and report the missing path rather than silently skip research.
- The module matrix is an intake router, not a replacement for the per-module Shape contract, user approval, or verification.
- `frontend-foundation` remains a future, separate change; no Vue files or FastAPI static-resource behavior changed here.

# Conclusion

Pass. The governance and routing artifacts satisfy the five current acceptance examples. The next implementation change is `frontend-foundation`, which will migrate the existing Web UI without adding M04 ownership functionality.
