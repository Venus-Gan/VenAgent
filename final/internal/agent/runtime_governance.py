from __future__ import annotations

import json
import logging
import time

from .cancel import CancelRegistry
from .status import infra_status as build_infra_status
from .status import status as build_status

logger = logging.getLogger(__name__)


class _NoopToken:
    def cancel(self) -> None:
        return None

    def is_cancelled(self) -> bool:
        return False


class RuntimeGovernance:
    """统一取消、快照和状态的轻量 façade。"""

    def __init__(self, agent) -> None:
        self.agent = agent

    def register(self):
        registry = self._cancel_registry()
        if registry is None:
            token = _NoopToken()
            return token, token.cancel
        return registry.register()

    def cancel(self) -> None:
        registry = self._cancel_registry()
        if registry is not None:
            registry.cancel_all()

    def current_task(self):
        registry = self._cancel_registry()
        if registry is None:
            return None
        return registry.current_task()

    def set_task(self, task) -> None:
        registry = self._cancel_registry()
        if registry is not None and hasattr(registry, "set_task"):
            registry.set_task(task)

    def append_snapshot(self, snapshot) -> None:
        registry = self._cancel_registry()
        if registry is not None and hasattr(registry, "append_snapshot"):
            registry.append_snapshot(snapshot)

    def snapshot_list(self):
        registry = self._cancel_registry()
        if registry is None:
            return []
        return registry.snapshot_list()

    def save_snapshot(self, task: dict) -> None:
        snapshot = dict(task) if isinstance(task, dict) else {}
        registry = self._cancel_registry()
        if registry is not None and isinstance(task, dict):
            registry.append_snapshot(dict(task))

        snapshot_repo = self._snapshot_repo()
        if snapshot_repo is None or not hasattr(snapshot_repo, "save"):
            return

        task_id = snapshot.get("task_id", f"task_{int(time.time())}")
        try:
            snapshot_repo.save(task_id, json.dumps(snapshot, ensure_ascii=False))
        except Exception as e:
            logger.warning("⚠️  快照写入失败: %s", e)

    def status(self):
        return build_status(self.agent)

    def infra_status(self):
        return build_infra_status(self.agent)

    def _cancel_registry(self) -> CancelRegistry | None:
        registry = getattr(self.agent, "_cancel_registry", None)
        if registry is None:
            return None
        return registry

    def _snapshot_repo(self):
        inf = getattr(self.agent, "inf", None)
        repo = getattr(inf, "repo", None) if inf is not None else None
        return getattr(repo, "snapshot", None) if repo is not None else None
