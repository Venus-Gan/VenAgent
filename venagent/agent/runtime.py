"""每个 AgentRun 独立 checkpoint 的 LangGraph 执行 runtime。"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator, Sequence

from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
)
from langgraph.checkpoint.base import BaseCheckpointSaver

from ..memory.errors import MemoryError
from ..memory.ports import MemoryStoreError
from ..memory.service import MemoryService, NaturalMemoryOutcome
from ..promptctx import (
    FOUNDATION_POLICY,
    ContextProjectionService,
    ProjectionInputCollector,
)
from .graph import RUNTIME_CONTRACT_VERSION, compile_agent_graph, run_config
from .observation import RunObservationHub
from .ports import MessageInvoker, RunStoreError
from .runs import (
    ActiveRunContext,
    AgentRun,
    AgentRunLifecycle,
    CancelToken,
    InvalidRunTransition,
    RunAuthorizationInvalid,
    RunCancelled,
)
from .state import FinalAnswer, RunFailure, RunState, TaskInput

MAX_MESSAGE_BYTES = 32 * 1024
MAX_STREAM_OUTPUT_BYTES = 128 * 1024
LEASE_DURATION = timedelta(seconds=60)
HEARTBEAT_INTERVAL_SECONDS = 15.0
CANCEL_OBSERVATION_INTERVAL_SECONDS = 0.5
MEMORY_SNAPSHOT_DEADLINE_SECONDS = 0.1
MEMORY_SHORT_TERM_DEADLINE_SECONDS = 0.15
MEMORY_LONG_TERM_DEADLINE_SECONDS = 0.15


class OutputLimitExceeded(RuntimeError):
    """模型输出超过单次运行预算。"""


class AgentRuntime:
    """scheduler、LangGraph 执行和实时观察的应用级协调器。"""

    def __init__(
        self,
        model: MessageInvoker,
        checkpointer: BaseCheckpointSaver,
        store: Any,
        *,
        memory: MemoryService | None = None,
        worker_id: str = "local-worker",
        poll_interval: float = 0.1,
        memory_snapshot_deadline: float = MEMORY_SNAPSHOT_DEADLINE_SECONDS,
        memory_short_term_deadline: float = MEMORY_SHORT_TERM_DEADLINE_SECONDS,
        memory_long_term_deadline: float = MEMORY_LONG_TERM_DEADLINE_SECONDS,
    ) -> None:
        self._model = model
        self._checkpointer = checkpointer
        self._store = store
        self._memory = memory
        self._lifecycle = AgentRunLifecycle(store)
        self._worker_id = worker_id
        self._poll_interval = poll_interval
        self._memory_snapshot_deadline = memory_snapshot_deadline
        self._memory_short_term_deadline = memory_short_term_deadline
        self._memory_long_term_deadline = memory_long_term_deadline
        self.hub = RunObservationHub()
        self._stop = asyncio.Event()
        self._worker_task: asyncio.Task[None] | None = None
        self._run_tasks: set[asyncio.Task[None]] = set()
        self._active: dict[str, ActiveRunContext] = {}
        self._loop: asyncio.AbstractEventLoop | None = None

    def start(self) -> None:
        if self._worker_task is None:
            self._loop = asyncio.get_running_loop()
            self._stop.clear()
            self._worker_task = asyncio.create_task(self._worker_loop())

    async def stop(self) -> None:
        self._stop.set()
        task = self._worker_task
        self._worker_task = None
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        for run_task in tuple(self._run_tasks):
            run_task.cancel()
        if self._run_tasks:
            await asyncio.gather(*self._run_tasks, return_exceptions=True)
        self._run_tasks.clear()
        self._loop = None

    def notify_cancel(self, run_id: str) -> None:
        loop = self._loop
        if loop is not None and loop.is_running():
            # FastAPI 的同步 route 在线程池中运行，必须回到 runtime 事件循环触发取消。
            loop.call_soon_threadsafe(self._notify_cancel_on_loop, run_id)
            return
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return
        self._notify_cancel_on_loop(run_id)

    def _notify_cancel_on_loop(self, run_id: str) -> None:
        active = self._active.get(run_id)
        if active is not None:
            active.token.cancel()
        asyncio.create_task(self.hub.publish(run_id, "cancel_requested"))

    async def delete_checkpoint(self, run_id: str) -> None:
        """业务删除收敛后只通过 checkpointer 公共接口清理 run 链。"""
        await self._checkpointer.adelete_thread(run_id)

    async def _worker_loop(self) -> None:
        while not self._stop.is_set():
            if len(self._run_tasks) >= 2:
                await asyncio.wait(
                    self._run_tasks,
                    timeout=self._poll_interval,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                continue
            now = datetime.now(timezone.utc)
            try:
                claimed = self._lifecycle.claim_next(
                    self._worker_id, now, LEASE_DURATION
                )
            except Exception:
                # claim 不确定时停止新工作；下一轮只重试数据库读取。
                await asyncio.sleep(self._poll_interval)
                continue
            if claimed is None:
                await asyncio.sleep(self._poll_interval)
                continue
            task = asyncio.create_task(self._execute(claimed))
            self._run_tasks.add(task)
            task.add_done_callback(self._consume_run_task)

    def _consume_run_task(self, task: asyncio.Task[None]) -> None:
        self._run_tasks.discard(task)
        with suppress(asyncio.CancelledError):
            task.exception()

    async def _execute(self, run: AgentRun) -> None:
        claim_token = run.claim_token or ""
        if run.cancel_requested_at is not None:
            cancelled = self._lifecycle.cancel(
                run.run_id,
                self._worker_id,
                claim_token,
                run.execution_attempt,
                "user_cancelled",
                datetime.now(timezone.utc),
            )
            if cancelled.status == "cancelled":
                await self.hub.publish(run.run_id, "cancelled")
            return
        active = ActiveRunContext(
            run.run_id,
            run.owner_id,
            claim_token,
            run.execution_attempt,
            CancelToken(),
        )
        self._active[run.run_id] = active
        heartbeat = asyncio.create_task(self._heartbeat(active))
        cancellation_observer = asyncio.create_task(
            self._observe_persistent_cancellation(active)
        )
        await self.hub.publish(run.run_id, "running")
        try:
            if run.runtime_contract_version != RUNTIME_CONTRACT_VERSION:
                incompatible = self._lifecycle.incompatible(
                    run.run_id,
                    claim_token,
                    run.execution_attempt,
                    "运行版本与当前 runtime 不兼容",
                    datetime.now(timezone.utc),
                )
                await self.hub.publish(
                    run.run_id,
                    "incompatible",
                    reason_code=incompatible.terminal_reason_code,
                )
                return
            execution_authorization = self._store.authorize_run(
                run.run_id, datetime.now(timezone.utc)
            )
            history = self._store.messages(run.owner_id, run.conversation_id)
            message = next(
                item for item in history if item.message_id == run.input_message_id
            )
            memory_authorization = (
                self._memory.run_authorization(execution_authorization, action="read")
                if self._memory is not None
                else None
            )
            graph = compile_agent_graph(
                self._answer_node(
                    run.run_id,
                    active,
                    history,
                    memory_authorization,
                    execution_authorization,
                ),
                self._checkpointer,
            )
            initial: RunState = {
                "task_input": TaskInput(message.message_id, message.content),
                "phase": "synthesizing",
                "node_outcomes": (),
                "approval_wait": None,
                "final_answer": None,
                "failure": None,
            }
            snapshot = await graph.aget_state(run_config(run.run_id))
            if isinstance(snapshot.values.get("final_answer"), FinalAnswer):
                # checkpoint 先于业务发布；接管者只重放幂等 finalizer。
                result = snapshot.values
            else:
                result = await self._invoke_graph(
                    graph,
                    initial,
                    run_config(run.run_id),
                    active,
                )
            final_answer = result.get("final_answer")
            failure = result.get("failure")
            if final_answer is not None and failure is not None:
                raise RuntimeError("final_answer and failure are mutually exclusive")
            if not isinstance(final_answer, FinalAnswer):
                if isinstance(failure, RunFailure):
                    self._lifecycle.fail(
                        run.run_id,
                        claim_token,
                        run.execution_attempt,
                        failure.code,
                        failure.message,
                        datetime.now(timezone.utc),
                    )
                    await self.hub.publish(run.run_id, "failed")
                    return
                raise RuntimeError("graph completed without a final answer")
            completed = self._lifecycle.succeed(
                run.run_id,
                claim_token,
                run.execution_attempt,
                final_answer.content,
                datetime.now(timezone.utc),
            )
            await self.hub.publish(
                run.run_id,
                "completed",
                output_message_id=completed.output_message_id,
            )
            if self._memory is not None and self._memory.natural_intent(message.content) is None:
                write_auth = self._memory.run_authorization(
                    execution_authorization, action="write"
                )
                try:
                    await asyncio.to_thread(
                        self._memory.enqueue_extraction,
                        write_auth,
                        message.content,
                        source_ref=f"message:{message.message_id}",
                        source_order=message.sequence,
                    )
                except (MemoryError, MemoryStoreError):
                    # 自动提取失败不改变已发布回答；状态面只暴露净化后的统计。
                    pass
        except RunCancelled:
            if active.lease_uncertain:
                return
            await self._reconcile_requested_cancel(run, active)
        except InvalidRunTransition:
            # finalizer 与取消并发时先对账取消；其他转换冲突按 fencing 失效处理。
            await self._reconcile_requested_cancel(run, active)
            return
        except RunAuthorizationInvalid:
            try:
                self._lifecycle.fail(
                    run.run_id,
                    claim_token,
                    run.execution_attempt,
                    "execution_authorization_invalid",
                    "运行授权已失效",
                    datetime.now(timezone.utc),
                )
            except InvalidRunTransition:
                return
            await self.hub.publish(run.run_id, "failed")
        except RunStoreError:
            # 数据库结果不确定时保留可接管状态，绝不伪造业务终态。
            active.lease_uncertain = True
            return
        except Exception:
            try:
                self._lifecycle.fail(
                    run.run_id,
                    claim_token,
                    run.execution_attempt,
                    "model_error",
                    "模型暂时不可用，请稍后重试",
                    datetime.now(timezone.utc),
                )
            except InvalidRunTransition:
                return
            await self.hub.publish(run.run_id, "failed")
        finally:
            for monitor in (heartbeat, cancellation_observer):
                monitor.cancel()
            await asyncio.gather(
                heartbeat,
                cancellation_observer,
                return_exceptions=True,
            )
            self._active.pop(run.run_id, None)

    async def _invoke_graph(
        self,
        graph: Any,
        initial: RunState,
        config: dict[str, dict[str, str]],
        active: ActiveRunContext,
    ) -> dict[str, Any]:
        graph_task = asyncio.create_task(graph.ainvoke(initial, config=config))
        active.execution_task = graph_task
        cancel_wait = asyncio.create_task(active.token.wait())
        try:
            done, _ = await asyncio.wait(
                {graph_task, cancel_wait}, return_when=asyncio.FIRST_COMPLETED
            )
            if cancel_wait in done:
                # 主动取消正在等待 provider 的协程，不能等下一 token 才轮询。
                graph_task.cancel()
                with suppress(asyncio.CancelledError):
                    await graph_task
                raise RunCancelled
            return graph_task.result()
        finally:
            active.execution_task = None
            if not graph_task.done():
                graph_task.cancel()
                with suppress(asyncio.CancelledError):
                    await graph_task
            cancel_wait.cancel()
            with suppress(asyncio.CancelledError):
                await cancel_wait

    async def _reconcile_requested_cancel(
        self, run: AgentRun, active: ActiveRunContext
    ) -> bool:
        if active.lease_uncertain:
            return False
        try:
            current = self._store.get_run_internal(run.run_id)
        except Exception:
            active.lease_uncertain = True
            return False
        if current is None or current.cancel_requested_at is None:
            return False
        try:
            cancelled = self._lifecycle.cancel(
                run.run_id,
                self._worker_id,
                active.claim_token,
                active.execution_attempt,
                "user_cancelled",
                datetime.now(timezone.utc),
            )
        except InvalidRunTransition:
            # 当前 claim 已丢失或 finalizer 已先提交，旧 worker 不发布终态。
            return False
        if cancelled.status != "cancelled":
            return False
        await self.hub.publish(run.run_id, "cancelled")
        return True

    def _answer_node(
        self,
        run_id: str,
        active: ActiveRunContext,
        history: tuple[Any, ...],
        memory_authorization: Any | None = None,
        execution_authorization: Any | None = None,
    ):
        async def answer(state: RunState) -> dict[str, Any]:
            task_input = state.get("task_input")
            if not isinstance(task_input, TaskInput):
                raise RuntimeError("run is missing task input")
            visible_history = history
            memory_blocks = ()
            natural_outcome: NaturalMemoryOutcome | None = None
            if (
                self._memory is not None
                and execution_authorization is not None
                and self._memory.natural_intent(task_input.content) is not None
            ):
                try:
                    natural_outcome = await asyncio.to_thread(
                        self._memory.process_natural_intent,
                        execution_authorization,
                        task_input.content,
                        source_ref=f"message:{task_input.input_message_id}",
                        source_order=next(
                            item.sequence
                            for item in history
                            if item.message_id == task_input.input_message_id
                        ),
                    )
                except Exception:
                    natural_outcome = NaturalMemoryOutcome(
                        self._memory.natural_intent(task_input.content) or "remember",
                        "unavailable",
                        reason_codes=("operation_unavailable",),
                    )
            if self._memory is not None and memory_authorization is not None:
                current_input = tuple(
                    item
                    for item in history
                    if item.message_id == task_input.input_message_id
                )
                try:
                    snapshot = await asyncio.wait_for(
                        asyncio.to_thread(
                            self._memory.capture_snapshot,
                            memory_authorization,
                            allow_disabled=True,
                        ),
                        timeout=self._memory_snapshot_deadline,
                    )
                except asyncio.TimeoutError:
                    self._memory.note_provider_timeout("memory-long-term")
                    snapshot = None
                    visible_history = current_input
                except Exception:
                    snapshot = None
                    visible_history = current_input
                if snapshot is not None:
                    try:
                        visible_history = await asyncio.wait_for(
                            asyncio.to_thread(
                                self._memory.conversation_context,
                                memory_authorization,
                                history,
                                task_input.input_message_id,
                                snapshot=snapshot,
                            ),
                            timeout=self._memory_short_term_deadline,
                        )
                        self._memory.note_provider_ready(
                            "memory-short-term", "conversation_context_ready"
                        )
                    except asyncio.TimeoutError:
                        self._memory.note_provider_timeout("memory-short-term")
                        visible_history = current_input
                    except Exception:
                        visible_history = current_input
                    try:
                        summary_blocks = await asyncio.wait_for(
                            asyncio.to_thread(
                                self._memory.summary_blocks,
                                memory_authorization,
                                history,
                                task_input.input_message_id,
                                snapshot=snapshot,
                            ),
                            timeout=self._memory_short_term_deadline,
                        )
                        self._memory.note_provider_ready(
                            "memory-short-term", "conversation_context_ready"
                        )
                    except asyncio.TimeoutError:
                        self._memory.note_provider_timeout("memory-short-term")
                        summary_blocks = ()
                    except Exception:
                        summary_blocks = ()
                    try:
                        long_term_blocks = await asyncio.wait_for(
                            asyncio.to_thread(
                                self._memory.context_blocks,
                                memory_authorization,
                                task_input.content,
                                snapshot=snapshot,
                            ),
                            timeout=self._memory_long_term_deadline,
                        )
                    except asyncio.TimeoutError:
                        self._memory.note_provider_timeout("memory-long-term")
                        long_term_blocks = ()
                    except Exception:
                        long_term_blocks = ()
                    memory_blocks = (*summary_blocks, *long_term_blocks)
            if natural_outcome is not None:
                memory_blocks = (*memory_blocks, natural_outcome.context_block(run_id))
            blocks = ProjectionInputCollector().collect(
                task_content=task_input.content,
                conversation_messages=tuple(
                    (item.role, item.content) for item in visible_history
                ),
                additional_blocks=memory_blocks,
            )
            projected = ContextProjectionService().project(
                FOUNDATION_POLICY, blocks, input_budget=32_000
            )
            messages: list[BaseMessage] = [
                *(SystemMessage(content=item) for item in projected.system_messages),
                *(HumanMessage(content=item) for item in projected.messages),
            ]
            parts: list[str] = []
            output_bytes = 0
            async for chunk in self._stream_model(messages):
                if active.token.is_cancelled():
                    raise RunCancelled
                delta = chunk_text(chunk)
                if not delta:
                    continue
                delta_bytes = len(delta.encode("utf-8"))
                if output_bytes + delta_bytes > MAX_STREAM_OUTPUT_BYTES:
                    raise OutputLimitExceeded
                output_bytes += delta_bytes
                parts.append(delta)
                await self.hub.publish(run_id, "token", content=delta)
            content = "".join(parts)
            if not content:
                raise RuntimeError("model returned no text")
            return {
                "phase": "synthesizing",
                "final_answer": FinalAnswer(content),
                "failure": None,
            }

        return answer

    async def _stream_model(
        self, messages: Sequence[BaseMessage]
    ) -> AsyncIterator[Any]:
        async_stream = getattr(self._model, "astream", None)
        if callable(async_stream):
            async for chunk in async_stream(messages):
                yield chunk
            return
        stream = getattr(self._model, "stream", None)
        if callable(stream):
            iterator = iter(stream(messages))
            while True:
                chunk = await asyncio.to_thread(_next_or_end, iterator)
                if chunk is _STREAM_END:
                    return
                yield chunk
        else:
            yield await asyncio.to_thread(self._model.invoke, messages)

    async def _heartbeat(self, active: ActiveRunContext) -> None:
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
            try:
                current = self._store.heartbeat(
                    active.run_id,
                    self._worker_id,
                    active.claim_token,
                    active.execution_attempt,
                    datetime.now(timezone.utc),
                    LEASE_DURATION,
                )
            except Exception:
                active.lease_uncertain = True
                active.token.cancel()
                return
            if current.cancel_requested_at is not None:
                active.token.cancel()
                return

    async def _observe_persistent_cancellation(self, active: ActiveRunContext) -> None:
        while True:
            await asyncio.sleep(CANCEL_OBSERVATION_INTERVAL_SECONDS)
            try:
                current = self._store.get_run_internal(active.run_id)
            except Exception:
                # 无法确认持久权威时停止当前协程，但不伪造取消终态。
                active.lease_uncertain = True
                active.token.cancel()
                return
            if current is None:
                active.lease_uncertain = True
                active.token.cancel()
                return
            if current.cancel_requested_at is not None:
                active.token.cancel()
                return


class _LocalModel:
    def invoke(self, messages: Sequence[BaseMessage]) -> AIMessage:
        latest = next(
            (item for item in reversed(messages) if isinstance(item, HumanMessage)),
            None,
        )
        if latest is None:
            return AIMessage(content="请先发送一条消息。")
        projected = message_text(latest)
        latest_user = next(
            (
                line.removeprefix("用户：")
                for line in reversed(projected.splitlines())
                if line.startswith("用户：")
            ),
            projected,
        )
        return AIMessage(content=f"我收到了：{latest_user}")

    async def astream(
        self, messages: Sequence[BaseMessage]
    ) -> AsyncIterator[AIMessageChunk]:
        content = message_text(self.invoke(messages))
        for character in content:
            await asyncio.sleep(0.03)
            yield AIMessageChunk(content=character)


def build_local_model() -> _LocalModel:
    """构建无凭据、无网络的默认模型适配器。"""

    return _LocalModel()


def message_text(message: BaseMessage) -> str:
    return str(message.text)


def chunk_text(chunk: Any) -> str:
    if isinstance(chunk, str):
        return chunk
    if isinstance(chunk, BaseMessage):
        return message_text(chunk)
    text = getattr(chunk, "text", None)
    return text if isinstance(text, str) else ""


_STREAM_END = object()


def _next_or_end(iterator: Any) -> Any:
    try:
        return next(iterator)
    except StopIteration:
        return _STREAM_END
