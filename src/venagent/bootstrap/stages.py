"""Bootstrap 阶段和安全诊断模型。"""

from dataclasses import dataclass
from enum import Enum

from .container import BootstrapDependencies


class BootstrapStage(str, Enum):
    CONFIG = "config"
    INFRASTRUCTURE = "infrastructure"
    APPLICATION = "application"
    APP = "app"


class StageStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class StageDiagnostic:
    """不包含原始异常、凭据或连接串的阶段诊断。"""

    stage: BootstrapStage
    status: StageStatus
    code: str = ""
    message: str = ""


@dataclass(frozen=True, slots=True)
class BootstrapResult:
    """Bootstrap 成功后的依赖和阶段报告。"""

    dependencies: BootstrapDependencies
    diagnostics: tuple[StageDiagnostic, ...]

    @property
    def app(self) -> object:
        return self.dependencies.app
