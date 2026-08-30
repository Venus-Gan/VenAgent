"""Artifact 引用存储：完整工具输出按内容寻址原子保存。"""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from .models import ArtifactRef


@dataclass
class FileArtifactStore:
    """把大输出写入本地 artifact 目录，只向模型/聊天返回引用与摘要。"""

    root: Path

    def save_text(self, source: str, content: str) -> ArtifactRef:
        self.root.mkdir(parents=True, exist_ok=True)
        artifact_id = str(uuid4())
        payload = content.encode("utf-8")
        checksum = hashlib.sha256(payload).hexdigest()
        path = self.root / artifact_id
        fd, temp_name = tempfile.mkstemp(
            prefix=f"{artifact_id}-", suffix=".tmp", dir=self.root
        )
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
        return ArtifactRef(
            artifact_id=artifact_id,
            source=source,
            size_bytes=len(payload),
            content_type="text/plain; charset=utf-8",
            checksum_sha256=checksum,
        )

    def load(self, artifact_id: str) -> bytes | None:
        path = self.root / artifact_id
        if not path.is_file():
            return None
        return path.read_bytes()
