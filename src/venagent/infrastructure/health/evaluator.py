"""从基础设施状态推导 capability health。"""

from collections.abc import Mapping
from dataclasses import dataclass

from .models import CapabilityHealth, CapabilityState, HealthSnapshot


@dataclass(frozen=True, slots=True)
class _CapabilitySpec:
    name: str
    dependencies: tuple[str, ...]
    durable: bool = False
    non_durable: bool = False
    allow_degraded: bool = False


_SPECS = (
    _CapabilitySpec("chat", ("llm",), non_durable=True),
    _CapabilitySpec("short_term_memory", (), non_durable=True),
    _CapabilitySpec("durable_memory", ("postgresql",), durable=True, allow_degraded=True),
    _CapabilitySpec("durable_workflow", ("postgresql",), durable=True),
    _CapabilitySpec(
        "rag",
        ("milvus", "elasticsearch", "llm"),
        non_durable=True,
    ),
    _CapabilitySpec("document", ("postgresql",), durable=True),
    _CapabilitySpec("graph_memory", ("neo4j",), non_durable=True, allow_degraded=True),
    _CapabilitySpec("sandbox", ("sandbox",), non_durable=True),
    _CapabilitySpec("events", ("kafka",), durable=True, allow_degraded=True),
)

_AVAILABLE = {"available", "connected", "ready", "enabled", "ok"}
_DISABLED = {"disabled", "off", "not_configured", "unconfigured"}


class CapabilityHealthEvaluator:
    """只基于注入状态计算能力快照，不连接任何外部服务。"""

    def __init__(self, dependency_status: Mapping[str, str]) -> None:
        self._dependency_status = dict(dependency_status)

    def evaluate(self) -> HealthSnapshot:
        return HealthSnapshot(tuple(self._evaluate_spec(spec) for spec in _SPECS))

    def _evaluate_spec(self, spec: _CapabilitySpec) -> CapabilityHealth:
        statuses = tuple(
            self._normalize(self._dependency_status.get(dependency, "unavailable"))
            for dependency in spec.dependencies
        )
        if any(status == "disabled" for status in statuses):
            return self._health(spec, CapabilityState.DISABLED, "DEPENDENCY_DISABLED")
        if any(status == "unavailable" for status in statuses):
            state = (
                CapabilityState.DEGRADED
                if spec.allow_degraded
                else CapabilityState.UNAVAILABLE
            )
            return self._health(spec, state, "DEPENDENCY_UNAVAILABLE")
        if any(status == "degraded" for status in statuses):
            return self._health(spec, CapabilityState.DEGRADED, "DEPENDENCY_DEGRADED")
        return self._health(spec, CapabilityState.AVAILABLE, "READY")

    @staticmethod
    def _normalize(status: str) -> str:
        value = str(status or "").strip().lower()
        if value in _DISABLED:
            return "disabled"
        if value in _AVAILABLE:
            return "available"
        if value == "degraded":
            return "degraded"
        return "unavailable"

    @staticmethod
    def _health(
        spec: _CapabilitySpec,
        state: CapabilityState,
        reason_code: str,
    ) -> CapabilityHealth:
        usable = state in {CapabilityState.AVAILABLE, CapabilityState.DEGRADED}
        return CapabilityHealth(
            capability=spec.name,
            state=state,
            dependencies=spec.dependencies,
            durable_available=usable and spec.durable and state is CapabilityState.AVAILABLE,
            non_durable_available=usable and spec.non_durable,
            reason_code=reason_code,
            diagnostic="capability health evaluated from injected dependency status",
        )
