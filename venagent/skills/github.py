"""GitHub Skill 广场的固定域名、有界发现与文件读取客户端。"""

from __future__ import annotations

import asyncio
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlencode

from .manifest import MAX_SKILL_BYTES

_REPO = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")


class SkillHubUnavailable(RuntimeError):
    pass


class SkillRateLimited(SkillHubUnavailable):
    pass


class SkillSourceNotFound(SkillHubUnavailable):
    pass


@dataclass(frozen=True)
class GitHubApiClient:
    base_url: str = "https://api.github.com"
    raw_base_url: str = "https://raw.githubusercontent.com"
    timeout_seconds: float = 10.0
    max_response_bytes: int = MAX_SKILL_BYTES

    async def search_repos(
        self,
        query: str,
        *,
        per_page: int = 20,
        token: str | None = None,
    ) -> list[dict[str, Any]]:
        params = {
            "q": f"{query.strip()} topic:venagent-skill".strip(),
            "sort": "stars",
            "order": "desc",
            "per_page": str(max(1, min(per_page, 20))),
        }
        data = await asyncio.to_thread(
            self._get_json,
            f"{self.base_url}/search/repositories?{urlencode(params)}",
            token,
        )
        items = data.get("items", [])
        return [item for item in items if isinstance(item, dict)]

    async def fetch_json_file(
        self, repo: str, path: str, *, token: str | None = None
    ) -> dict[str, Any]:
        raw = await self.fetch_file(repo, path, token=token)
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SkillHubUnavailable("skill_manifest_invalid") from exc
        if not isinstance(parsed, dict):
            raise SkillHubUnavailable("skill_manifest_invalid")
        return parsed

    async def fetch_file(
        self, repo: str, path: str, *, token: str | None = None
    ) -> bytes:
        if not _REPO.fullmatch(repo) or not path or ".." in path.split("/"):
            raise SkillHubUnavailable("skill_source_invalid")
        url = (
            f"{self.raw_base_url}/{quote(repo, safe='/')}/HEAD/"
            f"{quote(path, safe='/')}"
        )
        return await asyncio.to_thread(self._get_bytes, url, token)

    def _get_json(self, url: str, token: str | None) -> dict[str, Any]:
        raw = self._get_bytes(url, token)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SkillHubUnavailable("github_response_invalid") from exc
        if not isinstance(data, dict):
            raise SkillHubUnavailable("github_response_invalid")
        return data

    def _get_bytes(self, url: str, token: str | None) -> bytes:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "venagent",
                "Accept": "application/vnd.github+json",
            },
        )
        if token:
            request.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                body = response.read(self.max_response_bytes + 1)
                if len(body) > self.max_response_bytes:
                    raise SkillHubUnavailable("skill_source_too_large")
                return body
        except urllib.error.HTTPError as exc:
            if exc.code in {429, 403}:
                raise SkillRateLimited("github_rate_limited") from exc
            if exc.code == 404:
                raise SkillSourceNotFound("skill_source_not_found") from exc
            raise SkillHubUnavailable(f"github_error_{exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise SkillHubUnavailable("github_unreachable") from exc
