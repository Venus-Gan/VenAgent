# Backend ECC Audit

## Scope

Reviewed the current `venagent/` runtime, root `tests/`, `pyproject.toml`, and HTTP/configuration boundaries. The legacy `final/` reference implementation was excluded.

## Findings

### High: Chat input has no upper bound

- Location: `venagent/interfaces/http/schemas.py:13`, `venagent/agent/runtime.py:232`
- Evidence: `ChatRequest.message` is an unconstrained `str`, and `validated_message` checks only type and non-blank content. The request is then retained in conversation state and sent to the selected model.
- Impact: A client can submit an arbitrarily large request body, consuming worker memory and model context/billing before the application rejects it. The legacy-import path has explicit item and byte limits, so this is an inconsistent HTTP boundary.
- Remediation: Set an explicit message character/byte budget in the Pydantic request schema, enforce the same limit in the use case for non-HTTP callers, and add boundary tests.

### High: Test-only environment injection still reads local YAML configuration

- Location: `venagent/infra/llm/factory.py:18-20`, `venagent/infra/config/loader.py:75-85`
- Evidence: `build_runtime_loop(mapping)` passes the mapping to `load_config(environ=...)`, which deliberately skips `.env` but still loads `config/config.yaml` and `config/config.local.yaml`. The factory comment promises a no-file unit-test path. In the current checkout, `tests/test_llm.py` has four failures because local provider fields contaminate the supplied mapping.
- Impact: Test results vary with developer-local configuration; provider-specific tests can fail before reaching their assertions. This breaks the declared strict configuration contract and makes CI/local validation unreliable.
- Remediation: Make the `Mapping[str, str]` branch construct an isolated configuration from defaults plus that mapping only, or add an explicit no-file loader mode and cover it with a regression test.

### Medium: Streaming response accumulation is unbounded

- Location: `venagent/interfaces/http/streaming.py:43-51`
- Evidence: Every emitted delta is appended to `parts`, then joined into the terminal SSE event without a character or byte budget. Provider `max_tokens` is optional and cannot be relied on for custom adapters or all deployments.
- Impact: A long-running or faulty upstream stream can retain an unbounded response in process memory and duplicate it in the completed SSE event.
- Remediation: Set and enforce a maximum streamed-output budget, cancel the run with a stable terminal error when exceeded, and add an oversized-stream test.

### Medium: Required static quality and security checks are not reproducible from the dev extra

- Location: `pyproject.toml:20-23`
- Evidence: The declared `dev` extra installs only `httpx2` and `pytest`; the active virtual environment has no `ruff`, `mypy`, `bandit`, or `pip-audit`. Consequently the ECC Python lint, formatting, type, and Bandit checks cannot run.
- Impact: Style, type-safety, dependency, and static-security regressions have no reproducible local or CI gate.
- Remediation: Add the selected checkers to the development dependency group, configure them in `pyproject.toml`, and execute them in CI. Do not report their status as passing until installed and run.

### Low: Public SSE generator has an untyped run parameter

- Location: `venagent/interfaces/http/streaming.py:41`
- Evidence: `stream_events(service: ConversationService, run)` omits the type of `run`, despite the Python rule requiring annotations on all function signatures.
- Impact: Static checking cannot verify the `thread_id`, `run_id`, and cancellation members used by the generator.
- Remediation: Annotate it as `ConversationRun` and retain the existing return annotation.

## Checks

- `pytest -p no:cacheprovider --ignore tests/test_llm.py --ignore tests/test_persistence.py`: 44 passed.
- `pytest tests/test_persistence.py -p no:cacheprovider -vv`: 8 passed, 1 skipped because PostgreSQL integration is not configured.
- `pytest tests/test_llm.py -p no:cacheprovider -vv`: 47 passed, 4 failed due to the isolated-mapping defect above.
- Full `pytest -p no:cacheprovider`: timed out at 120 seconds after reaching the failing LLM group; it collected 104 tests.
- `ruff`, `mypy`, `bandit`, and `pip-audit`: unavailable in the installed environment.
- `npx --no-install ecc-agentshield scan --path venagent --format text`: timed out after 60 seconds without a result; no scanner finding is asserted.
