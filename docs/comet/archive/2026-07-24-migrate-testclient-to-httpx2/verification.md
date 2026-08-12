# Acceptance evidence

<!-- comet-native:acceptance-evidence:start -->
[
  {
    "acceptance_id": "acceptance-07eea3158c34ec9edb390f52af96dbd06f5ffc7c4281e5785c641d08af05d3e8",
    "evidence_refs": [
      "pyproject.toml"
    ]
  },
  {
    "acceptance_id": "acceptance-23809dda89121f95612da05c54f9378cfe1b1d75ce7e15cf1f6610299e4a8bb1",
    "evidence_refs": [
      "pyproject.toml"
    ]
  }
]
<!-- comet-native:acceptance-evidence:end -->

# Commands and results

- `.\.venv\Scripts\python.exe -m pip install -e ".[dev]"`：成功安装 `httpx2 2.9.0`、`httpcore2 2.9.0` 与 `truststore 0.10.4`，并重建 editable `venagent 0.1.0`。
- `.\.venv\Scripts\python.exe -m pytest -q -W default tests\test_api.py tests\test_streaming_api.py`：`13 passed in 12.22s`，无警告。
- `.\.venv\Scripts\python.exe -m pytest -q -W default`：`87 passed in 23.66s`，无 warnings summary，原 `StarletteDeprecationWarning` 消失。
- TestClient 后端检查：`testclient_backend=httpx2`，版本 `2.9.0`。
- `.\.venv\Scripts\python.exe -m pip check`：`No broken requirements found.`

# Skipped checks

- 未重复运行真实 provider 浏览器测试：本 change 仅替换测试开发依赖，不修改生产运行时或浏览器代码；M02 的交互式真实 provider 验收已在此前完成。

# Spec consistency

- 实现仅修改 `pyproject.toml` 的 `dev` 可选依赖，将直接测试依赖从 `httpx>=0.27,<1.0` 替换为 `httpx2>=2.0,<3.0`。
- Anthropic SDK 仍可传递安装其所需的 `httpx`；这不影响 Starlette TestClient 优先选择 `httpx2`，且 `pip check` 无冲突。
- 未修改生产依赖、应用代码、API/SSE 契约或 M02 canonical spec。

# Known limitations and risks

- 开发环境依赖未使用锁文件固定到补丁版本；当前约束允许兼容的 `httpx2` 2.x 后续版本。
- 本次验证针对当前解析得到的 `httpx2 2.9.0`。

# Conclusion

通过。TestClient 已迁移到 `httpx2` 首选路径，相关测试和全量 87 项测试均通过，弃用警告消失且依赖完整。
