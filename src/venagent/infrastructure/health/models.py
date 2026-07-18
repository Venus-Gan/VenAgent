"""不可变的 capability health DTO。"""

from dataclasses import dataclass
from enum import Enum
from typing import Any


class CapabilityState(str, Enum):
    AVAILABLE = "available"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    DISABLED = "disabled"


@dataclass(frozen=True, slots=True)
class CapabilityHealth:
    capability: str
    state: CapabilityState
    dependencies: tuple[str, ...] = ()
    durable_available: bool = False
    non_durable_available: bool = False
    reason_code: str = ""
    diagnostic: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "capability": self.capability,
            "state": self.state.value,
            "dependencies": list(self.dependencies),
            "durable_available": self.durable_available,
            "non_durable_available": self.non_durable_available,
            "reason_code": self.reason_code,
            "diagnostic": self.diagnostic,
        }


@dataclass(frozen=True, slots=True)
class HealthSnapshot:
    capabilities: tuple[CapabilityHealth, ...]

    def get(self, capability: str) -> CapabilityHealth:
        for item in self.capabilities:
            if item.capability == capability:
                return item
        raise KeyError(capability)

    def as_dict(self) -> dict[str, dict[str, Any]]:
        return {
            item.capability: item.as_dict()
            for item in self.capabilities
        }
