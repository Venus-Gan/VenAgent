"""同步/异步资源的统一生命周期管理。"""

import asyncio
import inspect
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True, slots=True)
class _RegisteredResource:
    name: str
    resource: object


class LifecycleError(RuntimeError):
    """不暴露原始异常文本的生命周期错误。"""

    code = "LIFECYCLE_RESOURCE_FAILED"

    def __init__(
        self,
        resource: str,
        phase: str,
        cleanup_failures: tuple[str, ...] = (),
    ) -> None:
        self.resource = resource
        self.phase = phase
        self.cleanup_failures = cleanup_failures
        super().__init__(f"lifecycle {phase} failed for {resource}")


class LifecycleManager:
    """按注册顺序启动资源，并按反序关闭已启动资源。"""

    def __init__(self, resources: Iterable[tuple[str, object]] = ()) -> None:
        self._resources: list[_RegisteredResource] = []
        self._started: list[_RegisteredResource] = []
        self._started_once = False
        self._closed = False
        for name, resource in resources:
            self.register(name, resource)

    @property
    def started(self) -> bool:
        return self._started_once and not self._closed

    def register(self, name: str, resource: object) -> None:
        if self._started_once:
            raise RuntimeError("cannot register resources after startup")
        if not name or not name.strip():
            raise ValueError("resource name must not be empty")
        if any(item.name == name for item in self._resources):
            raise ValueError(f"duplicate resource name: {name}")
        self._resources.append(_RegisteredResource(name=name, resource=resource))

    async def startup(self) -> None:
        if self._started_once:
            return
        self._started_once = True
        failed_resource: str | None = None
        cleanup_failures: tuple[str, ...] = ()
        try:
            for item in self._resources:
                # Track before invoking start so a partially initialized
                # resource is still given a chance to release its state.
                self._started.append(item)
                await self._invoke_start(item)
        except Exception:
            failed_resource = item.name
            cleanup_failures = await self.shutdown()
        except BaseException as error:
            cleanup_failures = await self.shutdown()
            if cleanup_failures:
                error.add_note(
                    "lifecycle startup cleanup failed for: "
                    + ", ".join(cleanup_failures)
                )
            raise
        if failed_resource is not None:
            raise LifecycleError(
                failed_resource,
                "startup",
                cleanup_failures=cleanup_failures,
            ) from None

    async def shutdown(self) -> tuple[str, ...]:
        if self._closed:
            return ()
        self._closed = True
        failures: list[str] = []
        for item in reversed(self._started):
            try:
                await self._invoke_close(item)
            except BaseException:
                failures.append(item.name)
        self._started.clear()
        return tuple(failures)

    async def _invoke_start(self, item: _RegisteredResource) -> None:
        start = getattr(item.resource, "start", None)
        if not callable(start):
            start = getattr(item.resource, "initialize_runtime", None)
        if not callable(start):
            return
        if inspect.iscoroutinefunction(start):
            result = start()
        else:
            result = await self._run_sync_hook(start)
        if inspect.isawaitable(result):
            await result

    async def _invoke_close(self, item: _RegisteredResource) -> None:
        close = getattr(item.resource, "close", None)
        if not callable(close):
            return
        if inspect.iscoroutinefunction(close):
            result = close()
        else:
            result = await self._run_sync_hook(close)
        if inspect.isawaitable(result):
            await result

    @staticmethod
    async def _run_sync_hook(hook):
        """Run a sync hook off-loop and drain it before propagating cancellation."""

        task = asyncio.create_task(asyncio.to_thread(hook))
        try:
            return await asyncio.shield(task)
        except BaseException:
            if not task.done():
                try:
                    await asyncio.shield(task)
                except BaseException:
                    pass
            raise
