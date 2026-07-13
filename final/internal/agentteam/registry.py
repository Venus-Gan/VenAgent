"""Generic preset registry for agentteam compat."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional

from .contracts import PresetContract


@dataclass(frozen=True, slots=True)
class PresetRegistration:
    """Pair a preset name, runnable instance, and its stable contract."""

    name: str
    runner: Any
    contract: PresetContract


class PresetRegistry:
    """Order-preserving registry for preset runners and their contracts."""

    def __init__(self, registrations: Iterable[PresetRegistration] | None = None) -> None:
        self._registrations: Dict[str, PresetRegistration] = {}
        self._order: list[str] = []
        self._lock = threading.RLock()
        if registrations is not None:
            for registration in registrations:
                self.register(registration.name, registration.runner, registration.contract)

    def register(self, name: str, runner: Any, contract: PresetContract) -> None:
        registration = PresetRegistration(name=name, runner=runner, contract=contract)
        with self._lock:
            if name not in self._registrations:
                self._order.append(name)
            self._registrations[name] = registration

    def get(self, name: str) -> Any | None:
        with self._lock:
            registration = self._registrations.get(name)
            return None if registration is None else registration.runner

    def names(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._order)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {name: self._registrations[name].runner for name in self._order}

    def contracts(self) -> dict[str, PresetContract]:
        with self._lock:
            return {name: self._registrations[name].contract for name in self._order}

    def get_contract(self, name: str) -> Optional[PresetContract]:
        with self._lock:
            registration = self._registrations.get(name)
            return None if registration is None else registration.contract
