# Acceptance evidence

<!-- comet-native:acceptance-evidence:start -->
[
  {
    "acceptance_id": "acceptance-871701e0fa8b7353a7b252cd3560e358449a44afddab0c3afc24b5572c26df5f",
    "evidence_refs": [
      "config/config.yaml",
      "venagent/infra/config/loader.py"
    ]
  },
  {
    "acceptance_id": "acceptance-be4660687801f0137d6a9d81e5bad8381ed12ef1f7e8049ec97b8bf0dfdf2f64",
    "evidence_refs": [
      "venagent/bootstrap.py",
      "venagent/infra/config/loader.py",
      "venagent/infra/platform/runtime.py"
    ]
  }
]
<!-- comet-native:acceptance-evidence:end -->

# Commands and results

- `.venv\\Scripts\\python.exe -m pytest -q tests\\test_persistence.py`: passed, `8 passed, 1 skipped in 37.56s`.
- `git diff --check`: passed; Git emitted only line-ending warnings for pre-existing worktree files.
- `comet native check preserve-legacy-secret-env-names --json`: passed; receipt `runtime/evidence/check-receipts/43ddde74e3b1e92d903c0397890dcf64e936993f6af0e10a72e3e8ac048eefcd.json`, eight files scanned and zero issues.

# Skipped checks

- `tests/test_config.py` and `tests/test_llm.py` were not run at the user's direction. Their follow-up update is deferred; this change only restores the runtime and documentation compatibility of existing `LLM_*` and `VENAGENT_DATABASE_URL` names.

# Spec consistency

- Non-sensitive provider, model, endpoint and tuning defaults remain in `config/config.yaml` and optional ignored `config/config.local.yaml`.
- Secrets and deployment overrides use `LLM_*` and `VENAGENT_DATABASE_URL` consistently in the loader, application bootstrap, runtime errors and Chinese documentation.

# Known limitations and risks

- The deferred configuration and LLM test suites still contain prior direct-cutover variable names and must be updated before they can validate the restored compatibility contract.

# Conclusion

Pass for the runtime, documentation and persistence scope. The two deferred suites are recorded explicitly rather than treated as passing.
