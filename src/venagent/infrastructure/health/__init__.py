"""框架无关的 capability 健康与降级模型。"""

from .evaluator import CapabilityHealthEvaluator
from .models import CapabilityHealth, CapabilityState, HealthSnapshot

__all__ = [
    "CapabilityHealth",
    "CapabilityHealthEvaluator",
    "CapabilityState",
    "HealthSnapshot",
]
