# Acceptance evidence

<!-- comet-native:acceptance-evidence:start -->
[
  {
    "acceptance_id": "acceptance-27521a3591efff66aede1ec7d382cadad906511be29cdf63400c1ee25f2315bc",
    "evidence_refs": [
      "tests/test_llm.py",
      "venagent/infra/llm/config.py"
    ]
  },
  {
    "acceptance_id": "acceptance-8f7066ded5bef21e83e864cc61e458b58994a17dae1f28baa9f7fd546477efcf",
    "evidence_refs": [
      "config/config.yaml",
      "venagent/infra/config/loader.py"
    ]
  },
  {
    "acceptance_id": "acceptance-9ff8456957f26abcccc696d4c0de6f48aebd0df4e261fb97a9972a23a2d15e3d",
    "evidence_refs": [
      "tests/test_config.py",
      "venagent/infra/config/loader.py"
    ]
  },
  {
    "acceptance_id": "acceptance-bf7fc62c254d369e8ba5c97135308b10a687d8e67c70546b63eb4132b02db64b",
    "evidence_refs": [
      "tests/test_config.py",
      "venagent/infra/config/loader.py"
    ]
  }
]
<!-- comet-native:acceptance-evidence:end -->

# Commands and results

- `.venv\\Scripts\\python.exe -m pytest -q tests\\test_config.py tests\\test_llm.py`: passed, `55 passed in 25.21s`.
- `.venv\\Scripts\\python.exe -m compileall -q venagent tests`: passed.
- `git diff --check -- pyproject.toml .gitignore .env.example README.md config venagent tests`: passed; Git emitted only pre-existing LF-to-CRLF warnings.
- `comet native check config-yaml-migration --json`: passed; receipt `runtime/evidence/check-receipts/0c44ae269794d34c58c3f6559884ef67c64e796f4af94ce661ebf6037e3790b3.json`, 17 files scanned and zero issues.

# Skipped checks

- The full HTTP/persistence suite was not run: its import path intentionally loads the local ignored `.env`, which still contains removed `LLM_PROVIDER` configuration and is now correctly rejected by the direct-cutover policy. The file was not read or modified because it can contain user secrets.

# Spec consistency

- `venagent.infra.config` owns YAML loading, secret rejection, typed environment overlay and a cached production snapshot.
- LLM and persistence bootstrap use this snapshot; old `LLM_*` and `VENAGENT_DATABASE_URL` are rejected without exposing their values.
- README, YAML templates and `.env.example` separate structured non-secret settings from secret injection.

# Known limitations and risks

- Before starting the application or full integration suite, the operator must migrate local `.env` names to `VENAGENT_LLM__*` and `VENAGENT_PERSISTENCE__DATABASE_URL` and move non-secret LLM settings into YAML.
- The current change deliberately does not implement future RAG/MCP configuration sections.

# Conclusion

Pass for the scoped configuration migration. Focused configuration and provider tests pass; the only skipped suite is blocked by the local secret file's expected pre-migration variable names.
