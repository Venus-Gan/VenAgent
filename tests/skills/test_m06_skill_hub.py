"""SkillHub 有界发现、TTL 缓存、并发合并与安装契约测试。

装配工厂（tool_control / SkillHub HTTP app）在 tests/skills/conftest.py 就近暴露。
保留契约：skill digest 校验、降级保持既有技能、rate-limit 重试一次、HTTP 层为
搜索/安装契约的权威断言层。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from venagent.skills.catalog import SkillCatalog
from venagent.skills.github import SkillHubUnavailable, SkillRateLimited
from venagent.skills.hub import SkillHubService
from venagent.skills.manifest import (
    SkillFile,
    SkillManifest,
    digest_sha256,
)

ORIGIN = {"Origin": "http://localhost:5173"}


class FakeGitHubClient:
    def __init__(
        self,
        *,
        items: list[dict[str, Any]] | None = None,
        content: bytes = b"# Research\n",
        fail_search: bool = False,
        rate_limited_once: bool = False,
        fail_repo: str | None = None,
    ) -> None:
        self.items = items or []
        self.content = content
        self.fail_search = fail_search
        self.rate_limited_once = rate_limited_once
        self.fail_repo = fail_repo
        self.search_calls = 0
        self.fetch_calls = 0
        self.manifest = {
            "schema_version": 1,
            "id": "research",
            "name": "Research",
            "version": "1.0.0",
            "description": "Research skill",
            "skill_sha256": digest_sha256(content),
            "compatible_runtimes": ["venagent"],
            "files": [],
        }

    async def search_repos(
        self,
        _query: str,
        *,
        per_page: int = 20,
        token: str | None = None,
    ) -> list[dict[str, Any]]:
        self.search_calls += 1
        if self.fail_search:
            raise SkillHubUnavailable("github_unreachable")
        if self.rate_limited_once and self.search_calls == 1:
            raise SkillRateLimited("github_rate_limited")
        return self.items

    async def fetch_json_file(
        self, repo: str, path: str, *, token: str | None = None
    ) -> dict[str, Any]:
        self.fetch_calls += 1
        return self.manifest

    async def fetch_file(
        self, repo: str, path: str, *, token: str | None = None
    ) -> bytes:
        self.fetch_calls += 1
        if self.fail_repo is not None and repo == self.fail_repo:
            from venagent.skills.github import SkillSourceNotFound

            raise SkillSourceNotFound("skill_source_not_found")
        return self.content


def test_skill_hub_search_uses_ttl_cache() -> None:
    client = FakeGitHubClient(
        items=[
            {
                "full_name": "owner/research",
                "description": "Research skill",
                "topics": ["venagent-skill"],
                "updated_at": "2026-08-01T00:00:00Z",
            }
        ]
    )
    service = SkillHubService(client)

    async def scenario() -> None:
        first = await service.search("research")
        second = await service.search("research")
        assert first == second
        assert len(first) == 1
        assert client.search_calls == 1

    asyncio.run(scenario())


def test_skill_hub_concurrent_refresh_is_merged() -> None:
    client = FakeGitHubClient(
        items=[
            {"full_name": "owner/a", "description": "A", "topics": [], "updated_at": None}
        ]
    )
    service = SkillHubService(client)

    async def scenario() -> None:
        results = await asyncio.gather(
            service.search("same"),
            service.search("same"),
            service.search("same"),
        )
        assert all(item == results[0] for item in results)
        assert client.search_calls == 1

    asyncio.run(scenario())


def test_skill_hub_install_validates_fixed_location_and_digest() -> None:
    client = FakeGitHubClient(
        content=b"# Research\n",
        items=[
            {
                "full_name": "owner/research",
                "description": "Research skill",
                "topics": ["venagent-skill"],
            }
        ],
    )
    service = SkillHubService(client)
    catalog = SkillCatalog()

    async def scenario() -> None:
        await service.search("research")
        item = await service.install("github:owner/research", catalog)
        assert item.skill_id == "research"
        assert item.manifest.digest_sha256 == digest_sha256(client.content)
        assert item.content == client.content.decode("utf-8")

    asyncio.run(scenario())


def test_skill_catalog_materializes_only_bound_declared_files(
    tmp_path: Path,
) -> None:
    instructions = b"# Script helper\n"
    script = b"printf skill-ok\n"
    manifest = SkillManifest(
        skill_id="script-helper",
        name="Script helper",
        version="1.0.0",
        description="Runs a bounded helper",
        digest_sha256=digest_sha256(instructions),
        source_url="test://script-helper",
        files=(SkillFile("scripts/analyze.sh", digest_sha256(script)),),
    )
    catalog = SkillCatalog(root=tmp_path / "skills")
    installed = catalog.install(
        manifest,
        manifest.digest_sha256,
        files={"SKILL.md": instructions, "scripts/analyze.sh": script},
    )
    catalog.bind_run("run-script", ("script-helper",))

    materializations = catalog.materializations_for_run("run-script")
    assert len(materializations) == 1
    assert materializations[0].package_digest == installed.package_digest
    assert materializations[0].files == (("scripts/analyze.sh", script),)

    package_file = (
        tmp_path
        / "skills"
        / "packages"
        / "script-helper"
        / installed.package_digest
        / "scripts"
        / "analyze.sh"
    )
    package_file.write_bytes(b"tampered")
    restarted = SkillCatalog(root=tmp_path / "skills")
    try:
        restarted.materializations_for_run("run-script")
    except ValueError as exc:
        assert str(exc) in {
            "skill file digest mismatch",
            "skill package digest mismatch",
        }
    else:
        raise AssertionError("tampered Skill package must fail closed")


def test_skill_hub_degrade_keeps_existing_skills() -> None:
    client = FakeGitHubClient(fail_search=True)
    service = SkillHubService(client)

    async def scenario() -> None:
        candidates = await service.search("anything")
        assert candidates == ()

    asyncio.run(scenario())


def test_skill_hub_rate_limit_retries_once() -> None:
    client = FakeGitHubClient(
        items=[
            {"full_name": "owner/a", "description": "A", "topics": [], "updated_at": None}
        ],
        rate_limited_once=True,
    )
    service = SkillHubService(client)

    async def scenario() -> None:
        candidates = await service.search("limited")
        assert len(candidates) == 1
        assert client.search_calls == 2
        assert service.degraded_reason is None

    asyncio.run(scenario())


def test_http_skill_hub_search_and_install(
    tmp_path: Path,
    skill_hub_app_factory,
) -> None:
    client = FakeGitHubClient(
        items=[
            {
                "full_name": "owner/research",
                "description": "Research skill",
                "topics": ["venagent-skill"],
                "updated_at": "2026-08-01T00:00:00Z",
            }
        ],
        content=b"# Research\n",
    )
    app = skill_hub_app_factory(tmp_path / "servers.json", client)
    with TestClient(app) as test_client:
        identity = test_client.post("/api/auth/guest", headers=ORIGIN).json()
        headers = {"Authorization": f"Bearer {identity['access_token']}"}
        searched = test_client.get(
            "/api/skills/hub", headers=headers, params={"query": "research"}
        )
        assert searched.status_code == 200
        assert searched.json()["items"][0]["repo_full_name"] == "owner/research"
        assert searched.json()["degraded"] is False
        installed = test_client.post(
            "/api/skills/hub/install",
            headers=headers,
            json={"skill_id": "github:owner/research"},
        )
        assert installed.status_code == 201
        assert installed.json()["skill_id"] == "research"
        skills = test_client.get("/api/skills", headers=headers)
        assert any(item["skill_id"] == "research" for item in skills.json())