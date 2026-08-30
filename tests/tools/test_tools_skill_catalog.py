"""M06 skill catalog 契约（单点）。

- digest 校验、安装与快照选择、缺失/坏 digest 拒绝：本文件单点。
"""

from __future__ import annotations

import pytest

from venagent.skills.catalog import SkillCatalog
from venagent.skills.manifest import SkillManifest, digest_sha256


def test_skill_catalog_validates_digest_and_snapshot() -> None:
    content = b"# skill\n"
    manifest = SkillManifest(
        skill_id="research",
        name="Research",
        version="1.0.0",
        description="Research skill",
        digest_sha256=digest_sha256(content),
        source_url="https://example.invalid/research",
    )
    catalog = SkillCatalog()
    catalog.install(manifest, digest_sha256(content), content=content.decode())
    with pytest.raises(ValueError):
        catalog.install(manifest, "bad-digest")
    snapshot = catalog.snapshot(("research",))
    assert snapshot.selected[0].skill_id == "research"
    assert snapshot.digest
    with pytest.raises(ValueError):
        catalog.snapshot(("missing",))