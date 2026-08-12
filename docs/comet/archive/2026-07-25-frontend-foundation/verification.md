# Acceptance evidence

<!-- comet-native:acceptance-evidence:start -->
[
  {
    "acceptance_id": "acceptance-a553820a70be577613fdceac7a3ab12dac412cf130ce0c540fd0ae5fa09179f8",
    "evidence_refs": [
      "web/playwright.config.ts",
      "web/tests/e2e/workspace.spec.ts"
    ]
  },
  {
    "acceptance_id": "acceptance-d35bd5973fece4b7620322e242005134a2641464a7c96c229add084eacdbf577",
    "evidence_refs": [
      "web/tests/e2e/workspace.spec.ts"
    ]
  },
  {
    "acceptance_id": "acceptance-e2b6b66079ae41c7d965616100f4abfe3a972d7ecedc59c65c95b79773eb99cf",
    "evidence_refs": [
      "web/tests/e2e/workspace.spec.ts"
    ]
  },
  {
    "acceptance_id": "acceptance-f07e73b134a816eb2ef50efb7bf20448976f5c9e671edbe677c0413debc5505d",
    "evidence_refs": [
      "tests/test_api.py",
      "venagent/interfaces/http/app.py",
      "venagent/interfaces/http/routes.py"
    ]
  }
]
<!-- comet-native:acceptance-evidence:end -->

# Commands and results

- `npm.cmd run build` in `web/`: passed. Vue type checking and Vite production build completed.
- `npm.cmd run test:e2e -- --reporter=line` in `web/`: passed, 5 tests. Used the locally installed Chrome through Playwright's `channel: 'chrome'`; covered create/delete, streaming completion, failed-message retry, cancellation, M03's restricted localStorage migration, and the mobile drawer.
- `.venv\\Scripts\\python.exe -m pytest -q`: passed, `99 passed, 1 skipped`.
- `.venv\\Scripts\\python.exe -m compileall -q venagent tests`: passed.
- `git diff --check -- .`: no whitespace errors; only pre-existing CRLF conversion warnings were reported.
- `comet native check frontend-foundation --json`: passed. Receipt: `runtime/evidence/check-receipts/310d61f810d5ffd675850c405338699fd0079da8fb01f735880b04c34d8d5ae5.json`; 36 text files scanned, 0 issues.

# Skipped checks

- The real PostgreSQL integration test remains skipped because `VENAGENT_TEST_DATABASE_URL` was not supplied to this verification run. It is intentionally separate from the application's `VENAGENT_DATABASE_URL`; this report does not treat the skipped test as passed.

# Spec consistency

- The root Vue app now renders through Vue Router, while the chat workspace and Pinia state remain in `modules/chat`.
- Vite continues to proxy the existing backend paths. Browser tests exercise the unchanged HTTP/SSE contracts, including cancellation and M03's restricted legacy browser-record migration.
- FastAPI serves `web/dist` only when both its index and asset directory are present; otherwise the root reports a stable `503 frontend_unavailable` response instead of falling back to a legacy page.
- The implementation retains only M03's explicit, confirmed localStorage-to-durable-thread migration. It does not restore dropped M03A library, archive, folder, branch, backup, export, or server-side history features.

# Known limitations and risks

- The user-selected infrastructure package name is `infra/platform`. The older canonical `feature-first-package-layout` specification still names `infra/persistence`; a separate architecture-document correction is needed so future modules do not inherit stale terminology.
- E2E uses deterministic mocked backend responses. API/SSE behavior is additionally covered by the Python regression suite, while real PostgreSQL integration needs the dedicated test database variable described above.

# Conclusion

Pass. The scoped frontend migration, static serving behavior, and covered browser workflows meet the four derived acceptance items. One external PostgreSQL integration check is honestly recorded as skipped.
