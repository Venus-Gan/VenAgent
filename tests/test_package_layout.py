"""tests/ 按模块镜像布局的约束（新目录树 draft §6 定稿，票 D3 重写）。

只断言文件/目录的**存在性**，不再断言被测包源码结构
（bases == []、行数上限、源码字符串 in content 已全部删除）。
tests/ 无 __init__.py，按 namespace package 工作；此处全部用 pathlib 路径存在性。
"""

from pathlib import Path

TESTS_ROOT = Path(__file__).resolve().parent

MODULE_DIRECTORIES = (
    "agent",
    "tools",
    "mcp",
    "skills",
    "memory",
    "repo",
    "llm",
    "config",
    "http",
    "ownership",
    "platform",
)


def test_tests_root_keeps_conftest_and_package_layout() -> None:
    assert (TESTS_ROOT / "conftest.py").is_file()
    assert (TESTS_ROOT / "test_package_layout.py").is_file()


def test_each_module_has_a_mirror_directory() -> None:
    for directory in MODULE_DIRECTORIES:
        assert (TESTS_ROOT / directory).is_dir(), (
            f"tests/{directory} 应作为模块镜像目录存在"
        )


def test_each_module_directory_contains_at_least_one_test_file() -> None:
    for directory in MODULE_DIRECTORIES:
        tests = sorted((TESTS_ROOT / directory).glob("test_*.py"))
        assert tests, f"tests/{directory} 应至少包含一个 test_*.py"


def test_mcp_fixture_provides_the_fake_server() -> None:
    assert (TESTS_ROOT / "mcp" / "fixtures" / "fake_mcp_server.py").is_file()


def test_tests_root_keeps_no_legacy_flat_test_files() -> None:
    flat_tests = sorted(
        path.name
        for path in TESTS_ROOT.glob("test_*.py")
        if path.name != "test_package_layout.py"
    )
    assert flat_tests == [], f"tests/ 根不应残留平铺 test_*.py：{flat_tests}"


def test_tests_root_is_a_namespace_package() -> None:
    # 依赖 pyproject.toml pythonpath=["."] 的 namespace 导入机制。
    assert not (TESTS_ROOT / "__init__.py").exists()