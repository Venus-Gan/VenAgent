"""标准 Skill 包 manifest、引用边界与摘要校验。"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

SKILL_MANIFEST_PATH = "skill.json"
SKILL_INSTRUCTIONS_PATH = "SKILL.md"
MAX_SKILL_FILES = 32
MAX_SKILL_BYTES = 1_048_576
_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


@dataclass(frozen=True)
class SkillFile:
    path: str
    digest_sha256: str


@dataclass(frozen=True)
class SkillManifest:
    skill_id: str
    name: str
    version: str
    description: str
    digest_sha256: str
    source_url: str
    compatible_runtimes: tuple[str, ...] = ("venagent",)
    size_bytes: int = 0
    files: tuple[SkillFile, ...] = ()


def parse_manifest(raw: Any, *, source_url: str) -> SkillManifest:
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise ValueError("skill manifest schema is unsupported")
    skill_id = str(raw.get("id", ""))
    name = str(raw.get("name", ""))
    version = str(raw.get("version", ""))
    description = str(raw.get("description", ""))
    digest = str(raw.get("skill_sha256", ""))
    runtimes = tuple(str(item) for item in raw.get("compatible_runtimes", ()))
    files_raw = raw.get("files", ())
    if (
        not _ID_PATTERN.fullmatch(skill_id)
        or not name
        or len(name) > 120
        or not version
        or len(version) > 64
        or len(description) > 500
        or not _is_digest(digest)
        or "venagent" not in runtimes
        or not isinstance(files_raw, list)
        or len(files_raw) > MAX_SKILL_FILES
    ):
        raise ValueError("skill manifest is invalid")
    files: list[SkillFile] = []
    seen = {SKILL_MANIFEST_PATH, SKILL_INSTRUCTIONS_PATH}
    for item in files_raw:
        if not isinstance(item, dict):
            raise ValueError("skill file entry is invalid")
        path = _safe_path(str(item.get("path", "")))
        file_digest = str(item.get("sha256", ""))
        if path in seen or not _is_digest(file_digest):
            raise ValueError("skill file entry is invalid")
        seen.add(path)
        files.append(SkillFile(path, file_digest))
    return SkillManifest(
        skill_id=skill_id,
        name=name,
        version=version,
        description=description,
        digest_sha256=digest,
        source_url=source_url,
        compatible_runtimes=runtimes,
        files=tuple(files),
    )


def validate_package(
    manifest: SkillManifest, files: dict[str, bytes]
) -> SkillManifest:
    instructions = files.get(SKILL_INSTRUCTIONS_PATH)
    if instructions is None or digest_sha256(instructions) != manifest.digest_sha256:
        raise ValueError("skill digest mismatch")
    expected = {item.path: item.digest_sha256 for item in manifest.files}
    if set(files) != {SKILL_INSTRUCTIONS_PATH, *expected}:
        raise ValueError("skill package file set mismatch")
    if sum(len(content) for content in files.values()) > MAX_SKILL_BYTES:
        raise ValueError("skill package is too large")
    for path, expected_digest in expected.items():
        if digest_sha256(files[path]) != expected_digest:
            raise ValueError("skill file digest mismatch")
    return SkillManifest(
        **{**manifest.__dict__, "size_bytes": sum(len(item) for item in files.values())}
    )


def validate_instructions(
    manifest: SkillManifest, instructions: bytes
) -> SkillManifest:
    """详情阶段只校验固定位置 SKILL.md，不提前抓取引用文件。"""
    if len(instructions) > MAX_SKILL_BYTES:
        raise ValueError("skill instructions are too large")
    if digest_sha256(instructions) != manifest.digest_sha256:
        raise ValueError("skill digest mismatch")
    return SkillManifest(**{**manifest.__dict__, "size_bytes": len(instructions)})


def digest_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _safe_path(value: str) -> str:
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or ".." in path.parts
        or "\\" in value
        or len(value) > 240
    ):
        raise ValueError("skill file path is invalid")
    return path.as_posix()


def _is_digest(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)
