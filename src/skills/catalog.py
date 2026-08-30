"""持久 Skill Catalog、版本包与每 Run 固定快照。"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
from dataclasses import asdict, dataclass
from pathlib import Path

from .manifest import SkillFile, SkillManifest, digest_sha256, validate_package


@dataclass(frozen=True)
class InstalledSkill:
    manifest: SkillManifest
    enabled: bool
    content: str = ""
    package_digest: str = ""
    package_files: tuple[tuple[str, bytes], ...] = ()

    @property
    def skill_id(self) -> str:
        return self.manifest.skill_id


@dataclass(frozen=True)
class SkillSnapshot:
    selected: tuple[InstalledSkill, ...]
    catalog: tuple[InstalledSkill, ...]
    digest: str


@dataclass(frozen=True)
class SkillMaterialization:
    skill_id: str
    package_digest: str
    files: tuple[tuple[str, bytes], ...]


class SkillCatalog:
    def __init__(
        self,
        installed: tuple[InstalledSkill, ...] = (),
        *,
        root: Path | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self._root = root
        self._installed = {item.skill_id: item for item in installed}
        self._versions = {
            (item.skill_id, item.package_digest or item.manifest.digest_sha256): item
            for item in installed
        }
        self._run_bindings: dict[str, tuple[tuple[str, str], ...]] = {}
        if root is not None:
            root.mkdir(parents=True, exist_ok=True)
            self._load()

    def install(
        self,
        manifest: SkillManifest,
        content_digest: str,
        *,
        content: str = "",
        files: dict[str, bytes] | None = None,
    ) -> InstalledSkill:
        package_files = files or {"SKILL.md": content.encode("utf-8")}
        if content_digest != manifest.digest_sha256:
            raise ValueError("skill digest mismatch")
        manifest = validate_package(manifest, package_files)
        package_digest = _package_digest(package_files)
        item = InstalledSkill(
            manifest=manifest,
            enabled=True,
            content=package_files["SKILL.md"].decode("utf-8"),
            package_digest=package_digest,
            package_files=tuple(sorted(package_files.items())),
        )
        if self._root is not None:
            self._write_package(item, package_files)
        with self._lock:
            self._installed[manifest.skill_id] = item
            self._versions[(item.skill_id, item.package_digest)] = item
            self._persist_index()
        return item

    def uninstall(self, skill_id: str) -> bool:
        with self._lock:
            removed = self._installed.pop(skill_id, None)
            if removed is not None:
                self._persist_index()
        return removed is not None

    def set_enabled(self, skill_id: str, enabled: bool) -> InstalledSkill:
        with self._lock:
            current = self._installed[skill_id]
            item = InstalledSkill(
                manifest=current.manifest,
                enabled=enabled,
                content=current.content,
                package_digest=current.package_digest,
                package_files=current.package_files,
            )
            self._installed[skill_id] = item
            self._persist_index()
            return item

    def list(self) -> tuple[InstalledSkill, ...]:
        with self._lock:
            return tuple(self._installed.values())

    def snapshot(self, selected_ids: tuple[str, ...]) -> SkillSnapshot:
        with self._lock:
            catalog = tuple(
                item
                for item in self._installed.values()
                if item.enabled and "venagent" in item.manifest.compatible_runtimes
            )
        indexed = {item.skill_id: item for item in catalog}
        selected: list[InstalledSkill] = []
        for skill_id in selected_ids:
            item = indexed.get(skill_id)
            if item is None:
                raise ValueError(f"skill unavailable: {skill_id}")
            selected.append(item)
        payload = "\n".join(
            f"{item.skill_id}:{item.package_digest or item.manifest.digest_sha256}"
            for item in selected
        )
        return SkillSnapshot(tuple(selected), catalog, digest_sha256(payload.encode()))

    def bind_run(self, run_id: str, selected_ids: tuple[str, ...]) -> SkillSnapshot:
        snapshot = self.snapshot(selected_ids)
        binding = tuple(
            (item.skill_id, item.package_digest or item.manifest.digest_sha256)
            for item in snapshot.selected
        )
        with self._lock:
            self._run_bindings[run_id] = binding
            self._persist_runs()
        return snapshot

    def snapshot_for_run(self, run_id: str) -> SkillSnapshot:
        with self._lock:
            binding = self._run_bindings.get(run_id, ())
        selected = tuple(self._load_version(skill_id, digest) for skill_id, digest in binding)
        catalog = self.snapshot(()).catalog
        payload = "\n".join(f"{item.skill_id}:{item.package_digest}" for item in selected)
        return SkillSnapshot(selected, catalog, digest_sha256(payload.encode()))

    def release_run(self, run_id: str) -> None:
        with self._lock:
            binding = self._run_bindings.pop(run_id, None)
            if binding is not None:
                self._persist_runs()

    def materializations_for_run(
        self, run_id: str
    ) -> tuple[SkillMaterialization, ...]:
        materializations: list[SkillMaterialization] = []
        for item in self.snapshot_for_run(run_id).selected:
            if not item.manifest.files:
                continue
            package_files = self._read_and_validate_package(item)
            declared = tuple(
                (reference.path, package_files[reference.path])
                for reference in item.manifest.files
            )
            materializations.append(
                SkillMaterialization(
                    skill_id=item.skill_id,
                    package_digest=item.package_digest,
                    files=declared,
                )
            )
        return tuple(materializations)

    def _read_and_validate_package(
        self, item: InstalledSkill
    ) -> dict[str, bytes]:
        if item.package_files:
            files = dict(item.package_files)
        else:
            if self._root is None:
                raise ValueError("skill package files unavailable")
            target = (
                self._root
                / "packages"
                / item.skill_id
                / item.package_digest
            )
            target_root = target.resolve()
            files = {}
            for relative in ("SKILL.md", *(ref.path for ref in item.manifest.files)):
                path = target / Path(relative)
                if (
                    path.is_symlink()
                    or not path.is_file()
                    or not path.resolve().is_relative_to(target_root)
                ):
                    raise ValueError("skill package file is unsafe")
                files[relative] = path.read_bytes()
        validate_package(item.manifest, files)
        if _package_digest(files) != item.package_digest:
            raise ValueError("skill package digest mismatch")
        return files

    def _write_package(self, item: InstalledSkill, files: dict[str, bytes]) -> None:
        assert self._root is not None
        target = self._root / "packages" / item.skill_id / item.package_digest
        if target.is_dir():
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".install-", dir=target.parent))
        try:
            for relative, content in files.items():
                path = staging / Path(relative)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
            (staging / "manifest-record.json").write_text(
                json.dumps(
                    _manifest_json(item.manifest), ensure_ascii=False, indent=2
                ),
                encoding="utf-8",
            )
            os.replace(staging, target)
        finally:
            if staging.exists():
                shutil.rmtree(staging)

    def _load_version(self, skill_id: str, package_digest: str) -> InstalledSkill:
        current = self._installed.get(skill_id)
        if current is not None and current.package_digest == package_digest:
            return current
        retained = self._versions.get((skill_id, package_digest))
        if retained is not None:
            return retained
        if self._root is None:
            raise ValueError("skill snapshot version unavailable")
        target = self._root / "packages" / skill_id / package_digest
        raw = json.loads((target / "manifest-record.json").read_text(encoding="utf-8"))
        manifest = _manifest_from_record(raw)
        item = InstalledSkill(
            manifest,
            True,
            (target / "SKILL.md").read_text(encoding="utf-8"),
            package_digest,
        )
        self._versions[(skill_id, package_digest)] = item
        return item

    def _load(self) -> None:
        assert self._root is not None
        index = self._root / "installed.json"
        if index.is_file():
            raw = json.loads(index.read_text(encoding="utf-8"))
            for entry in raw.get("skills", ()):
                item = self._load_version(entry["skill_id"], entry["package_digest"])
                self._installed[item.skill_id] = InstalledSkill(
                    item.manifest,
                    bool(entry["enabled"]),
                    item.content,
                    item.package_digest,
                    item.package_files,
                )
        runs = self._root / "run-bindings.json"
        if runs.is_file():
            raw = json.loads(runs.read_text(encoding="utf-8"))
            self._run_bindings = {
                run_id: tuple((str(a), str(b)) for a, b in binding)
                for run_id, binding in raw.get("runs", {}).items()
            }

    def _persist_index(self) -> None:
        if self._root is None:
            return
        _atomic_json(
            self._root / "installed.json",
            {
                "skills": [
                    {
                        "skill_id": item.skill_id,
                        "package_digest": item.package_digest,
                        "enabled": item.enabled,
                    }
                    for item in self._installed.values()
                ]
            },
        )

    def _persist_runs(self) -> None:
        if self._root is not None:
            _atomic_json(self._root / "run-bindings.json", {"runs": self._run_bindings})


def _package_digest(files: dict[str, bytes]) -> str:
    payload = b"".join(
        path.encode() + b"\0" + digest_sha256(content).encode() + b"\0"
        for path, content in sorted(files.items())
    )
    return digest_sha256(payload)


def _manifest_json(manifest: SkillManifest) -> dict[str, object]:
    raw = asdict(manifest)
    raw["files"] = [asdict(item) for item in manifest.files]
    return raw


def _manifest_from_record(raw: dict[str, object]) -> SkillManifest:
    return SkillManifest(
        skill_id=str(raw["skill_id"]),
        name=str(raw["name"]),
        version=str(raw["version"]),
        description=str(raw["description"]),
        digest_sha256=str(raw["digest_sha256"]),
        source_url=str(raw["source_url"]),
        compatible_runtimes=tuple(raw.get("compatible_runtimes", ())),
        size_bytes=int(raw.get("size_bytes", 0)),
        files=tuple(SkillFile(**item) for item in raw.get("files", ())),
    )


def _atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
