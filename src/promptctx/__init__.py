"""模型调用上下文的通用契约与确定性装配。"""

from .assembler import ContextProjectionService
from .context import BudgetReport, ContextBlock, ModelCallContext
from .errors import (
    ContextOverflow,
    ContextProjectionError,
    ProjectionConfigurationError,
)
from .schema import FOUNDATION_POLICY, ProjectionPolicy, SectionSpec
from .source import ContextSource, ContextSourceStatus, ProjectionInputCollector

__all__ = [
    "BudgetReport",
    "ContextBlock",
    "ContextOverflow",
    "ContextProjectionError",
    "ContextProjectionService",
    "ContextSource",
    "ContextSourceStatus",
    "FOUNDATION_POLICY",
    "ModelCallContext",
    "ProjectionConfigurationError",
    "ProjectionInputCollector",
    "ProjectionPolicy",
    "SectionSpec",
]
