"""基础设施启动状态与自然语言报告。"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass
from enum import StrEnum


class InfrastructureState(StrEnum):
    """跨基础设施统一的启动结果。"""

    READY = "ready"
    DEGRADED = "degraded"
    DISABLED = "disabled"
    FAILED = "failed"


@dataclass(frozen=True)
class InfrastructureStatus:
    """一个基础设施的机器状态与安全运维文案。"""

    component: str
    state: InfrastructureState
    reason_code: str
    operator_message: str
    health_status: str
    required: bool = False


@dataclass(frozen=True)
class StartupReport:
    """composition root 完成装配后产生的启动快照。"""

    mode: str
    infrastructure: tuple[InfrastructureStatus, ...]


_LEVELS = {
    InfrastructureState.READY: logging.INFO,
    InfrastructureState.DEGRADED: logging.WARNING,
    InfrastructureState.DISABLED: logging.INFO,
    InfrastructureState.FAILED: logging.ERROR,
}
_MODE_LABELS = {
    "durable": "持久化",
    "degraded": "降级",
}


def log_startup_report(
    report: StartupReport,
    *,
    logger: logging.Logger,
) -> None:
    """输出组件无关的自然语言状态和最终汇总。"""
    counts = Counter(status.state for status in report.infrastructure)

    # 报告器只消费 adapter 已确认的事实，不在输出阶段重新探测基础设施。
    for status in report.infrastructure:
        logger.log(
            _LEVELS[status.state],
            status.operator_message,
            extra={
                "component": status.component,
                "state": status.state.value,
                "reason_code": status.reason_code,
                "required": status.required,
            },
        )

    summary_level = max(
        (_LEVELS[status.state] for status in report.infrastructure),
        default=logging.INFO,
    )
    logger.log(
        summary_level,
        (
            "基础设施初始化完成：%d 项可用、%d 项降级、%d 项未启用、%d 项失败。"
            "VenAgent 将以%s模式启动。"
        ),
        counts[InfrastructureState.READY],
        counts[InfrastructureState.DEGRADED],
        counts[InfrastructureState.DISABLED],
        counts[InfrastructureState.FAILED],
        _MODE_LABELS.get(report.mode, report.mode),
        extra={"mode": report.mode},
    )
