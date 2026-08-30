"""随 VenAgent 发布的官方精选标准 Skill 包。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .manifest import (
    SKILL_INSTRUCTIONS_PATH,
    SKILL_MANIFEST_PATH,
    SkillManifest,
    parse_manifest,
    validate_package,
)


@dataclass(frozen=True)
class FeaturedSkillPackage:
    manifest: SkillManifest
    files: dict[str, bytes]


def load_featured_packages() -> tuple[FeaturedSkillPackage, ...]:
    root = Path(__file__).with_name("featured")
    packages: list[FeaturedSkillPackage] = []
    for directory in sorted(path for path in root.iterdir() if path.is_dir()):
        manifest_path = directory / SKILL_MANIFEST_PATH
        instructions_path = directory / SKILL_INSTRUCTIONS_PATH
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        files = {SKILL_INSTRUCTIONS_PATH: instructions_path.read_bytes()}
        manifest = parse_manifest(raw, source_url=f"builtin:{directory.name}")
        packages.append(FeaturedSkillPackage(validate_package(manifest, files), files))
    return tuple(packages)
