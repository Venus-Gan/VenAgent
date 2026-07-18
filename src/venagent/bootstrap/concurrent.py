"""可注入的并发启动任务编排。"""

from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Iterable


class TaskStatus(str, Enum):
    """单个启动任务的公开状态。"""

    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class BootstrapTask:
    """一个无参数、可注入的启动任务。"""

    name: str
    callback: Callable[[], object]

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("task name must not be empty")
        if not callable(self.callback):
            raise TypeError("task callback must be callable")


@dataclass(frozen=True, slots=True)
class TaskResult:
    """不携带原始异常的任务结果。"""

    name: str
    status: TaskStatus
    value: object = field(default=None, repr=False)
    code: str = ""
    message: str = ""


@dataclass(frozen=True, slots=True)
class ConcurrentBootstrapResult:
    """按输入顺序保存的并发启动结果。"""

    results: tuple[TaskResult, ...]

    @property
    def failures(self) -> tuple[TaskResult, ...]:
        return tuple(item for item in self.results if item.status is TaskStatus.FAILED)

    @property
    def succeeded(self) -> tuple[TaskResult, ...]:
        return tuple(item for item in self.results if item.status is TaskStatus.SUCCEEDED)


class ConcurrentBootstrapper:
    """并发执行独立任务，并在全部任务结束后执行可选 barrier。"""

    def __init__(
        self,
        tasks: Iterable[BootstrapTask],
        *,
        barrier: Callable[[ConcurrentBootstrapResult], object] | None = None,
    ) -> None:
        self._tasks = tuple(tasks)
        self._validate_tasks(self._tasks)
        if barrier is not None and not callable(barrier):
            raise TypeError("barrier must be callable")
        self._barrier = barrier

    def run(self) -> ConcurrentBootstrapResult:
        if not self._tasks:
            result = ConcurrentBootstrapResult(results=())
            if self._barrier is not None:
                self._barrier(result)
            return result

        futures: list[Future[object]] = []
        with ThreadPoolExecutor(
            max_workers=len(self._tasks),
            thread_name_prefix="bootstrap",
        ) as executor:
            futures = [executor.submit(task.callback) for task in self._tasks]
            future_to_task = dict(zip(futures, self._tasks))
            completed: dict[str, TaskResult] = {}
            try:
                # 先按完成顺序收集，避免慢任务阻塞后续任务的失败归类；
                # 最终仍按声明顺序返回，保证调用方结果稳定。
                for future in as_completed(futures):
                    task = future_to_task[future]
                    completed[task.name] = self._collect_result(task, future)
            except BaseException:
                # 已运行的 Python 线程不能被安全强杀；取消尚未开始的任务，
                # 再由 executor 上下文等待所有已运行任务结束，避免遗留 worker。
                for future in futures:
                    future.cancel()
                raise
            results = tuple(completed[task.name] for task in self._tasks)

        result = ConcurrentBootstrapResult(results=results)
        if self._barrier is not None:
            self._barrier(result)
        return result

    @staticmethod
    def _collect_result(
        task: BootstrapTask,
        future: Future[object],
    ) -> TaskResult:
        try:
            return TaskResult(
                name=task.name,
                status=TaskStatus.SUCCEEDED,
                value=future.result(),
                code="TASK_READY",
                message="task initialized",
            )
        except Exception:
            return TaskResult(
                name=task.name,
                status=TaskStatus.FAILED,
                code="TASK_INITIALIZATION_FAILED",
                message="task initialization failed",
            )

    @staticmethod
    def _validate_tasks(tasks: tuple[BootstrapTask, ...]) -> None:
        names = [task.name for task in tasks]
        if len(names) != len(set(names)):
            raise ValueError("duplicate task names are not allowed")
