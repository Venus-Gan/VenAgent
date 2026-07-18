"""按固定顺序执行依赖装配的最小 Bootstrapper。"""

from collections.abc import Callable
import inspect

from .container import BootstrapDependencies, DependencyContainer
from .stages import BootstrapResult, BootstrapStage, StageDiagnostic, StageStatus


class BootstrapError(RuntimeError):
    """以稳定阶段信息报告失败，避免把原始异常内容暴露给调用方。"""

    code = "BOOTSTRAP_STAGE_FAILED"

    def __init__(
        self,
        stage: BootstrapStage,
        diagnostics: tuple[StageDiagnostic, ...],
        cleanup_failures: tuple[str, ...] = (),
    ) -> None:
        self.stage = stage
        self.diagnostics = diagnostics
        self.cleanup_failures = cleanup_failures
        super().__init__(f"bootstrap stage failed: {stage.value}")


class StagedBootstrapper:
    """执行配置确认、基础设施、应用和 HTTP app 四个装配阶段。"""

    def __init__(self, container: DependencyContainer) -> None:
        self._container = container

    def run(self) -> BootstrapResult:
        diagnostics: list[StageDiagnostic] = [
            StageDiagnostic(
                stage=BootstrapStage.CONFIG,
                status=StageStatus.SUCCEEDED,
                code="CONFIG_READY",
                message="validated configuration is ready",
            )
        ]

        created: list[object] = []
        try:
            infrastructure = self._execute(
                BootstrapStage.INFRASTRUCTURE,
                self._container.infrastructure_factory,
                (self._container.config,),
                diagnostics,
            )
            created.append(infrastructure)
            application = self._execute(
                BootstrapStage.APPLICATION,
                self._container.application_factory,
                (self._container.config, infrastructure),
                diagnostics,
            )
            created.append(application)
            app = self._execute(
                BootstrapStage.APP,
                self._container.app_factory,
                (self._container.config, infrastructure, application),
                diagnostics,
            )
        except BootstrapError as error:
            cleanup_failures = self._cleanup(created)
            if cleanup_failures:
                raise BootstrapError(
                    error.stage,
                    error.diagnostics,
                    cleanup_failures=cleanup_failures,
                ) from None
            raise
        except BaseException as error:
            # Cancellation and process interrupts must not skip best-effort
            # cleanup, but the original control-flow signal must propagate.
            cleanup_failures = self._cleanup(created)
            if cleanup_failures:
                cleanup_names = ", ".join(cleanup_failures)
                error.add_note(f"bootstrap cleanup failed for: {cleanup_names}")
            raise

        dependencies = BootstrapDependencies(
            config=self._container.config,
            infrastructure=infrastructure,
            application=application,
            app=app,
        )
        return BootstrapResult(
            dependencies=dependencies,
            diagnostics=tuple(diagnostics),
        )

    def _execute(
        self,
        stage: BootstrapStage,
        factory: Callable[..., object],
        args: tuple[object, ...],
        diagnostics: list[StageDiagnostic],
    ) -> object:
        failed = False
        try:
            value = factory(*args)
            if inspect.isawaitable(value):
                self._discard_awaitable(value)
                raise TypeError("async factory is not supported by sync bootstrapper")
        except Exception:
            failed = True

        if failed:
            diagnostics.append(
                StageDiagnostic(
                    stage=stage,
                    status=StageStatus.FAILED,
                    code=BootstrapError.code,
                    message=f"{stage.value} stage initialization failed",
                )
            )
            # Construct and raise after leaving the exception handler so the
            # public error cannot retain the original exception as context.
            raise BootstrapError(stage, tuple(diagnostics))

        diagnostics.append(
            StageDiagnostic(
                stage=stage,
                status=StageStatus.SUCCEEDED,
                code=f"{stage.value.upper()}_READY",
                message=f"{stage.value} stage initialized",
            )
        )
        return value

    @staticmethod
    def _discard_awaitable(value: object) -> None:
        cancel = getattr(value, "cancel", None)
        if callable(cancel):
            cancel()
        close = getattr(value, "close", None)
        if callable(close):
            close()

    @classmethod
    def _cleanup(cls, created: list[object]) -> tuple[str, ...]:
        failures: list[str] = []
        for resource in reversed(created):
            close = getattr(resource, "close", None)
            if not callable(close):
                continue
            try:
                result = close()
                if inspect.isawaitable(result):
                    cls._discard_awaitable(result)
                    failures.append(type(resource).__name__)
            except BaseException:
                failures.append(type(resource).__name__)
        return tuple(failures)
