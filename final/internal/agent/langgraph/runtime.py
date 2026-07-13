
from __future__ import annotations

import copy
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional

from internal.graph.task_graph import NodeStatus, TaskGraph

from ..graph_runtime import GraphConfig, GraphResult, GraphRuntime, NodeResult


@dataclass(frozen=True)
class ReactCheckpoint:
    thread_id: str
    task: Dict[str, Any] = field(default_factory=dict)
    nodes: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)


class InMemorySaver:
    """Minimal checkpoint store keyed by thread id."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._history: Dict[str, List[ReactCheckpoint]] = {}

    def save(self, thread_id: str, checkpoint: ReactCheckpoint) -> None:
        if not thread_id:
            return
        with self._lock:
            self._history.setdefault(thread_id, []).append(copy.deepcopy(checkpoint))

    def get(self, thread_id: str) -> Optional[ReactCheckpoint]:
        if not thread_id:
            return None
        with self._lock:
            history = self._history.get(thread_id, [])
            return copy.deepcopy(history[-1]) if history else None

    def load(self, thread_id: str) -> Optional[ReactCheckpoint]:
        return self.get(thread_id)

    def history(self, thread_id: str) -> List[ReactCheckpoint]:
        if not thread_id:
            return []
        with self._lock:
            return copy.deepcopy(self._history.get(thread_id, []))

    def list(self) -> List[ReactCheckpoint]:
        with self._lock:
            snapshots: List[ReactCheckpoint] = []
            for history in self._history.values():
                snapshots.extend(copy.deepcopy(history))
            return snapshots

    def clear(self, thread_id: str) -> None:
        if not thread_id:
            return
        with self._lock:
            self._history.pop(thread_id, None)


class ReactRuntime(GraphRuntime):
    """Checkpoint-aware wrapper around the react graph runtime."""

    def __init__(
        self,
        graph: TaskGraph,
        agent,
        cfg: GraphConfig,
        tools: Dict[str, Any],
        task: Optional[dict] = None,
        on_event: Optional[Any] = None,
        checkpointer: Optional[InMemorySaver] = None,
        thread_id: Optional[str] = None,
    ) -> None:
        super().__init__(graph, agent, cfg, tools, task=task, on_event=on_event)
        self.checkpointer = checkpointer or InMemorySaver()
        self.thread_id = thread_id or str(self.task.get('task_id') or self.task.get('thread_id') or '')

    def invoke(self, token, config: Optional[Mapping[str, Any]] = None, *, resume: bool = False) -> GraphResult:
        self.thread_id = _resolve_thread_id(config, self.thread_id or self.task.get('task_id') or self.task.get('thread_id') or '')
        if not self.thread_id:
            raise ValueError('thread_id is required for checkpointed react runtime')

        if resume:
            self._restore_checkpoint()
        else:
            self._reset_graph_state()
            if hasattr(self.checkpointer, 'clear'):
                self.checkpointer.clear(self.thread_id)

        return super().execute(token)

    def resume(self, token, config: Optional[Mapping[str, Any]] = None) -> GraphResult:
        return self.invoke(token, config=config, resume=True)

    def _save_snapshot(self) -> None:
        super()._save_snapshot()
        self._persist_checkpoint()

    def _persist_checkpoint(self) -> None:
        if not self.thread_id:
            return
        checkpoint = ReactCheckpoint(
            thread_id=self.thread_id,
            task=copy.deepcopy(self.task),
            nodes=_snapshot_nodes(self.graph),
        )
        self.checkpointer.save(self.thread_id, checkpoint)

    def _restore_checkpoint(self) -> None:
        checkpoint = self.checkpointer.get(self.thread_id)
        if checkpoint is None:
            return
        self.task = copy.deepcopy(checkpoint.task)
        _restore_nodes(self.graph, checkpoint.nodes)

    def _reset_graph_state(self) -> None:
        for node in self.graph.nodes.values():
            node.status = NodeStatus.PENDING
            node.result = ''
            node.error = ''
            node.retry_count = 0


def _resolve_thread_id(config: Optional[Mapping[str, Any]], fallback: str) -> str:
    if isinstance(config, Mapping):
        configurable = config.get('configurable')
        if isinstance(configurable, Mapping):
            thread_id = configurable.get('thread_id') or configurable.get('threadId')
            if thread_id:
                return str(thread_id)
        thread_id = config.get('thread_id')
        if thread_id:
            return str(thread_id)
    return str(fallback or '')


def _snapshot_nodes(graph: TaskGraph) -> Dict[str, Dict[str, Any]]:
    snapshot: Dict[str, Dict[str, Any]] = {}
    for node_id, node in graph.nodes.items():
        snapshot[node_id] = {
            'status': node.status.value if hasattr(node.status, 'value') else str(node.status),
            'result': node.result,
            'error': node.error,
            'retry_count': node.retry_count,
        }
    return snapshot


def _restore_nodes(graph: TaskGraph, snapshot: Mapping[str, Mapping[str, Any]]) -> None:
    for node_id, payload in snapshot.items():
        node = graph.nodes.get(node_id)
        if node is None:
            continue
        status_value = str(payload.get('status', NodeStatus.PENDING.value))
        try:
            node.status = NodeStatus(status_value)
        except Exception:
            node.status = NodeStatus.PENDING
        node.result = str(payload.get('result', ''))
        node.error = str(payload.get('error', ''))
        retry_count = payload.get('retry_count', 0)
        try:
            node.retry_count = int(retry_count)
        except Exception:
            node.retry_count = 0
