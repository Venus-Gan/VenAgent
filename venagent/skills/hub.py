"""受控 Skill 广场：缓存、降级、标准包详情与原子安装。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .catalog import InstalledSkill, SkillCatalog
from .featured import FeaturedSkillPackage, load_featured_packages
from .github import GitHubApiClient, SkillHubUnavailable, SkillRateLimited
from .manifest import (
    SKILL_INSTRUCTIONS_PATH,
    SKILL_MANIFEST_PATH,
    SkillManifest,
    parse_manifest,
    validate_instructions,
    validate_package,
)

DEFAULT_CACHE_TTL = timedelta(minutes=30)


@dataclass(frozen=True)
class SkillHubCandidate:
    skill_id: str
    name: str
    description: str
    source: str
    repo_full_name: str = ""
    topics: tuple[str, ...] = ()
    stars: int = 0
    source_url: str = ""
    updated_at: str | None = None


@dataclass(frozen=True)
class SkillHubDetail:
    candidate: SkillHubCandidate
    manifest: SkillManifest
    preview: str


@dataclass
class _CacheEntry:
    created_at: datetime
    candidates: tuple[SkillHubCandidate, ...]


@dataclass
class SkillHubService:
    client: GitHubApiClient
    enabled: bool = True
    token: str | None = None
    search_query: str = "agent skill instructions"
    max_items: int = 20
    cache_ttl: timedelta = DEFAULT_CACHE_TTL
    degraded_reason: str | None = None
    stale: bool = False
    featured_packages: tuple[FeaturedSkillPackage, ...] = field(
        default_factory=load_featured_packages
    )
    _cache: dict[str, _CacheEntry] = field(default_factory=dict)
    _locks: dict[str, asyncio.Lock] = field(default_factory=dict)

    def featured(self) -> tuple[SkillHubCandidate, ...]:
        return tuple(
            SkillHubCandidate(
                skill_id=item.manifest.skill_id,
                name=item.manifest.name,
                description=item.manifest.description,
                source="official",
                source_url=item.manifest.source_url,
            )
            for item in self.featured_packages
        )

    async def search(self, query: str = "") -> tuple[SkillHubCandidate, ...]:
        if not self.enabled:
            self.degraded_reason = "skill_hub_disabled"
            self.stale = False
            return ()
        normalized = query.strip()[:80].casefold()
        key = normalized or "default"
        self.degraded_reason = None
        self.stale = False
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            cached = self._cache.get(key)
            now = datetime.now(timezone.utc)
            if cached is not None and now - cached.created_at < self.cache_ttl:
                return cached.candidates
            search_query = " ".join(
                item for item in (self.search_query, normalized) if item
            )
            try:
                items = await self.client.search_repos(
                    search_query, per_page=self.max_items, token=self.token
                )
            except SkillRateLimited:
                await asyncio.sleep(1.0)
                try:
                    items = await self.client.search_repos(
                        search_query, per_page=self.max_items, token=self.token
                    )
                except SkillHubUnavailable as exc:
                    return self._degraded(cached, str(exc))
            except SkillHubUnavailable as exc:
                return self._degraded(cached, str(exc))
            candidates = tuple(
                SkillHubCandidate(
                    skill_id=f"github:{item['full_name']}",
                    name=str(item["full_name"]).rsplit("/", 1)[-1],
                    source="github",
                    repo_full_name=str(item["full_name"]),
                    description=str(item.get("description") or ""),
                    topics=tuple(str(topic) for topic in item.get("topics", ())),
                    stars=int(item.get("stargazers_count", 0)),
                    source_url=str(item.get("html_url") or ""),
                    updated_at=item.get("updated_at"),
                )
                for item in items
                if item.get("full_name")
            )[: self.max_items]
            self._cache[key] = _CacheEntry(now, candidates)
            if len(self._locks) > 128:
                self._locks = {key: lock}
            return candidates

    async def detail(self, skill_id: str) -> SkillHubDetail:
        candidate = self._candidate(skill_id)
        if candidate.source == "official":
            package = self._featured_package(skill_id)
            return SkillHubDetail(
                candidate=candidate,
                manifest=package.manifest,
                preview=package.files[SKILL_INSTRUCTIONS_PATH]
                .decode("utf-8", errors="replace")[:1000],
            )
        source_url = candidate.source_url or f"https://github.com/{candidate.repo_full_name}"
        raw_manifest, instructions = await asyncio.gather(
            self.client.fetch_json_file(
                candidate.repo_full_name, SKILL_MANIFEST_PATH, token=self.token
            ),
            self.client.fetch_file(
                candidate.repo_full_name, SKILL_INSTRUCTIONS_PATH, token=self.token
            ),
        )
        manifest = parse_manifest(raw_manifest, source_url=source_url)
        manifest = validate_instructions(manifest, instructions)
        return SkillHubDetail(
            candidate=candidate,
            manifest=manifest,
            preview=instructions.decode("utf-8", errors="replace")[:1000],
        )

    async def install(self, skill_id: str, catalog: SkillCatalog) -> InstalledSkill:
        detail = await self.detail(skill_id)
        candidate = detail.candidate
        if candidate.source == "official":
            package = self._featured_package(skill_id)
            return catalog.install(
                package.manifest,
                package.manifest.digest_sha256,
                content=package.files[SKILL_INSTRUCTIONS_PATH].decode("utf-8"),
                files=dict(package.files),
            )
        files = {
            SKILL_INSTRUCTIONS_PATH: await self.client.fetch_file(
                candidate.repo_full_name, SKILL_INSTRUCTIONS_PATH, token=self.token
            )
        }
        for reference in detail.manifest.files:
            files[reference.path] = await self.client.fetch_file(
                candidate.repo_full_name, reference.path, token=self.token
            )
        manifest = validate_package(detail.manifest, files)
        return catalog.install(
            manifest,
            manifest.digest_sha256,
            content=files[SKILL_INSTRUCTIONS_PATH].decode("utf-8"),
            files=files,
        )

    def _candidate(self, skill_id: str) -> SkillHubCandidate:
        for candidate in self.featured():
            if candidate.skill_id == skill_id:
                return candidate
        for cached in self._cache.values():
            for candidate in cached.candidates:
                if candidate.skill_id == skill_id:
                    return candidate
        raise SkillHubUnavailable("skill_candidate_not_found")

    def _featured_package(self, skill_id: str) -> FeaturedSkillPackage:
        for package in self.featured_packages:
            if package.manifest.skill_id == skill_id:
                return package
        raise SkillHubUnavailable("skill_candidate_not_found")

    def _degraded(
        self, cached: _CacheEntry | None, reason: str
    ) -> tuple[SkillHubCandidate, ...]:
        self.degraded_reason = reason
        self.stale = cached is not None
        return cached.candidates if cached is not None else ()
