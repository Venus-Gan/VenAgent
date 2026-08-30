"""每个 AgentRun 独立 checkpoint 的 LangGraph 执行 runtime。"""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator, Sequence

from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.types import Command, interrupt

from ..memory.errors import MemoryError
from ..memory.ports import MemoryStoreError
from ..memory.service import MemoryService, NaturalMemoryOutcome
from ..promptctx import (
    FOUNDATION_POLICY,
    ContextProjectionService,
    ProjectionInputCollector,
)
from ..tools.control import ToolControlContext
from ..tools.langchain import (
    ModelToolCallInvalid,
    model_tool_calls_from_chunks,
)
from .events import AssistantBlockAssembler, normalize_assistant_chunk
from .graph import RUNTIME_CONTRACT_VERSION, compile_agent_graph, run_config
from .observation import RunObservationHub
from .planning import PlanningNodes, task_without_plan_prefix
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
from .state import (
    ClarificationAnswer,
    FinalAnswer,
    PendingToolCallRef,
    RunFailure,
    RunState,
    TaskInput,
    ToolObservationRef,
)

MAX_MESSAGE_BYTES = 32 * 1024
MAX_STREAM_OUTPUT_BYTES = 128 * 1024
LEASE_DURATION = timedelta(seconds=60)
HEARTBEAT_INTERVAL_SECONDS = 15.0
CANCEL_OBSERVATION_INTERVAL_SECONDS = 0.5
MEMORY_SNAPSHOT_DEADLINE_SECONDS = 0.1
MEMORY_SHORT_TERM_DEADLINE_SECONDS = 0.15
MEMORY_LONG_TERM_DEADLINE_SECONDS = 0.15

logger = logging.getLogger(__name__)


class OutputLimitExceeded(RuntimeError):
    """模型输出超过单次运行预算。"""


class ModelPhaseError(RuntimeError):
    """把模型阶段暴露给安全诊断日志，同时保留原始异常类型。"""

    def __init__(self, phase: str, cause: Exception) -> None:
        super().__init__(str(cause))
        self.phase = phase
        self.cause = cause


class AgentRuntime:
    """scheduler、LangGraph 执行和实时观察的应用级协调器。"""

    def __init__(
        self,
        model: MessageInvoker,
        checkpointer: BaseCheckpointSaver,
        store: Any,
        *,
        memory: MemoryService | None = None,
        tool_control: ToolControlContext | None = None,
        planning: Any | None = None,
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
        self._tool_control = tool_control
        self._planning = planning
        self._lifecycle = AgentRunLifecycle(store)
        self._worker_id = worker_id
        self._poll_interval = poll_interval
        self._memory_snapshot_deadline = memory_snapshot_deadline
        self._memory_short_term_deadline = memory_short_term_deadline
        self._memory_long_term_deadline = memory_long_term_deadline
        self.hub = RunObservationHub(store)
        self._stop = asyncio.Event()
        self._worker_task: asyncio.Task[None] | None = None
        self._run_tasks: set[asyncio.Task[None]] = set()
        self._active: dict[str, ActiveRunContext] = {}
        self._pending_clarifications: dict[str, ClarificationAnswer] = {}
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
        asyncio.create_task(self.hub.publish(run_id, "run.cancel_requested"))

    async def delete_checkpoint(self, run_id: str) -> None:
        """业务删除收敛后只通过 checkpointer 公共接口清理 run 链。"""
        await self._checkpointer.adelete_thread(run_id)

    def cancel_waiting_approval(self, owner_id: str, run_id: str) -> AgentRun:
        """将 waiting_approval Run 原子转为 cancelled（无活跃 worker）。"""
        return self._lifecycle.cancel_waiting_approval(
            owner_id,
            run_id,
            datetime.now(timezone.utc),
        )

    def decide_approval(
        self,
        owner_id: str,
        approval_id: str,
        approved: bool,
        *,
        rejected_reason: str | None = None,
    ) -> tuple[Any, AgentRun | None, bool, bool]:
        """收敛审批决定入口：先写权威 Approval，再 CAS resume。"""
        if self._tool_control is None:
            raise RuntimeError("tool_control is not configured")
        item, changed, conflict = self._tool_control.approvals.decide_detailed(
            approval_id,
            owner_id,
            approved,
            rejected_reason=rejected_reason,
        )
        if conflict or not changed:
            return item, self._store.get_run_internal(item.run_id), changed, conflict
        run = None
        try:
            run = self._lifecycle.resume(item.run_id, datetime.now(timezone.utc))
        except InvalidRunTransition:
            run = self._store.get_run_internal(item.run_id)
        return item, run, changed, conflict

    async def finalize_cancelled_run(self, run_id: str, owner_id: str) -> None:
        """取消后的统一资源清理与事件发布。"""
        if self._tool_control is not None:
            await self._tool_control.finalize_cancelled_run(run_id, owner_id)
        await self.hub.publish(run_id, "run.cancelled")

    def resume_run(self, run_id: str) -> None:
        """审批决定后把等待中的 Run 重新放入队列，由 worker 恢复同一 thread。"""
        self._lifecycle.resume(run_id, datetime.now(timezone.utc))

    def submit_clarification(
        self, owner_id: str, run_id: str, answer: ClarificationAnswer
    ) -> AgentRun:
        """澄清答复入口：暂存答案并 resume，worker 以 Command(resume=answer) 恢复。

        v1 限制：答案仅存进程内存，worker 重启丢失后用户需重新提交。
        """
        run = self._store.get_run_internal(run_id)
        if run is None or run.owner_id != owner_id:
            raise RunAuthorizationInvalid()
        if run.status != "waiting_approval":
            raise InvalidRunTransition("run is not waiting for clarification")
        self._pending_clarifications[run_id] = answer
        return self._lifecycle.resume(run_id, datetime.now(timezone.utc))

    async def publish_tool_event(
        self, run_id: str, kind: str, payload: dict[str, Any]
    ) -> None:
        """把 Gateway 的脱敏 tool 事件发布到 SSE 观察面。"""
        await self.hub.publish(run_id, "tool.event", kind=kind, **payload)

    def run_events(
        self, owner_id: str, run_id: str, *, after_sequence: int = 0
    ) -> tuple[Any, ...]:
        return self._store.run_events(
            owner_id, run_id, after_sequence=after_sequence
        )

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
                await self.hub.publish(run.run_id, "run.cancelled")
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
        await self.hub.publish(
            run.run_id,
            "run.started",
            execution_attempt=run.execution_attempt,
            phase="synthesizing",
        )
        waiting_hitl: str | None = None
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
                    "run.incompatible",
                    reason_code=incompatible.terminal_reason_code,
                )
                return
            execution_authorization = self._store.authorize_run(
                run.run_id, datetime.now(timezone.utc)
            )
            if self._tool_control is not None:
                await self._tool_control.start_run(run.run_id)
            history = self._store.messages(run.owner_id, run.conversation_id)
            message = next(
                item for item in history if item.message_id == run.input_message_id
            )
            plan_content, plan_mode = task_without_plan_prefix(message.content)
            memory_authorization = (
                self._memory.run_authorization(execution_authorization, action="read")
                if self._memory is not None
                else None
            )
            node_bundle = (
                self._tool_nodes(
                    run.run_id,
                    run.owner_id,
                    active,
                    history,
                    memory_authorization,
                    execution_authorization,
                )
                if self._tool_control is not None
                else None
            )
            planning_nodes: PlanningNodes | None = None
            task_input = TaskInput(
                message.message_id, plan_content, plan_mode=plan_mode
            )
            if (
                self._planning is not None
                and node_bundle is not None
                and self._planning.enabled
            ):
                # 每 run 一次统一装配计划层记忆前缀（AGI-saber memPrefix 同构；
                # 四节点复用，run 内不重投影）。降级口径见方法注释。
                mem_prefix = await self._build_planning_mem_prefix(
                    run_id=run.run_id,
                    history=history,
                    memory_authorization=memory_authorization,
                    task_input=task_input,
                )
                planning_nodes = self._planning.build_nodes(
                    run_id=run.run_id,
                    owner_id=run.owner_id,
                    active=active,
                    execution_attempt=run.execution_attempt,
                    publish=self.hub.publish,
                    mem_prefix=mem_prefix,
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
                prepare_node=node_bundle["prepare"] if node_bundle else None,
                model_decision_node=(
                    node_bundle["model_decision"] if node_bundle else None
                ),
                execute_tool_node=(
                    node_bundle["execute_tool"] if node_bundle else None
                ),
                model_finalize_node=(
                    node_bundle["model_finalize"] if node_bundle else None
                ),
                final_node=node_bundle["final"] if node_bundle else None,
                selector_node=planning_nodes.selector if planning_nodes else None,
                planner_node=planning_nodes.planner if planning_nodes else None,
                executor_node=planning_nodes.executor if planning_nodes else None,
                replanner_node=planning_nodes.replanner if planning_nodes else None,
                generator_node=planning_nodes.generator if planning_nodes else None,
                rag_answer_node=planning_nodes.rag_answer if planning_nodes else None,
            )
            initial: RunState = {
                "task_input": task_input,
                "phase": "synthesizing",
                "plan": None,
                "plan_branch": None,
                "replan_action": None,
                "replans_used": 0,
                "node_outcomes": (),
                "clarification_request": None,
                "clarification_answer": None,
                "approval_wait": None,
                "natural_memory_outcome": None,
                "pending_tool_call": None,
                "tool_observation": None,
                "final_answer": None,
                "failure": None,
            }
            snapshot = await graph.aget_state(run_config(run.run_id))
            if isinstance(snapshot.values.get("final_answer"), FinalAnswer):
                # checkpoint 先于业务发布；接管者只重放幂等 finalizer。
                result = snapshot.values
            elif snapshot.next and snapshot.values.get("pending_tool_call") is not None:
                result = await self._invoke_graph(
                    graph,
                    initial,
                    run_config(run.run_id),
                    active,
                    resume="decided",
                )
            elif snapshot.next and run.run_id in self._pending_clarifications:
                answer = self._pending_clarifications.pop(run.run_id)
                result = await self._invoke_graph(
                    graph,
                    initial,
                    run_config(run.run_id),
                    active,
                    resume=answer,
                )
            elif snapshot.next and snapshot.values.get("plan") is not None:
                # 计划 run 的审批中断挂在 executor 节点：恢复时必须以
                # Command(resume) 续跑，绝不能当新输入重跑整图（会重建计划）。
                result = await self._invoke_graph(
                    graph,
                    initial,
                    run_config(run.run_id),
                    active,
                    resume="decided",
                )
            else:
                result = await self._invoke_graph(
                    graph,
                    initial,
                    run_config(run.run_id),
                    active,
                )
            if "__interrupt__" in result:
                waiting_hitl = self._wait_for_interrupt(run, active, result)
                return
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
                    await self.hub.publish(run.run_id, "run.failed")
                    return
                raise RuntimeError("graph completed without a final answer")
            completed = self._lifecycle.succeed(
                run.run_id,
                claim_token,
                run.execution_attempt,
                final_answer.content,
                datetime.now(timezone.utc),
                final_answer.blocks,
            )
            await self.hub.publish(
                run.run_id,
                "assistant.message",
                output_message_id=completed.output_message_id,
                blocks=list(final_answer.blocks),
            )
            await self.hub.publish(
                run.run_id,
                "run.completed",
                output_message_id=completed.output_message_id,
            )
            if self._memory is not None and self._memory.natural_intent(message.content) is None:
                write_auth = self._memory.run_authorization(
                    execution_authorization, action="write"
                )
                try:
                    await asyncio.to_thread(
                        self._memory.record_user_message_for_consolidation,
                        write_auth,
                        conversation_id=message.conversation_id,
                        sequence=message.sequence,
                        now=None,
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
            await self.hub.publish(run.run_id, "run.failed")
        except RunStoreError:
            # 数据库结果不确定时保留可接管状态，绝不伪造业务终态。
            active.lease_uncertain = True
            return
        except Exception as exc:
            # 提供详细的错误信息（包括 HTTP 状态码），但避免泄露敏感凭据
            cause = exc.cause if isinstance(exc, ModelPhaseError) else exc
            phase = exc.phase if isinstance(exc, ModelPhaseError) else "runtime"
            error_type = type(cause).__name__
            
            # 尝试提取 HTTP 状态码（仅接受有效的整数 HTTP 状态码）
            status_code = None
            candidates = (
                getattr(cause, "status_code", None),
                getattr(getattr(cause, "response", None), "status_code", None),
                getattr(cause, "code", None),
            )
            for candidate in candidates:
                if isinstance(candidate, int) and 100 <= candidate <= 599:
                    status_code = candidate
                    break
            
            # 构建详细的用户可见错误消息
            error_message = "模型调用失败"
            
            # 添加 HTTP 状态码（如果有）
            if status_code:
                error_message += f"（HTTP {status_code}）"
                # 添加常见状态码的说明
                status_descriptions = {
                    400: "请求格式错误",
                    401: "API 密钥无效或已过期",
                    402: "账户余额不足",
                    403: "无权访问此资源",
                    404: "API 端点不存在",
                    429: "请求频率超限",
                    500: "服务器内部错误",
                    502: "网关错误",
                    503: "服务暂时不可用",
                    504: "网关超时",
                }
                if status_code in status_descriptions:
                    error_message += f" - {status_descriptions[status_code]}"
            else:
                error_message += f"：{error_type}"
            
            # 添加阶段信息
            if phase != "runtime":
                error_message += f"（阶段：{phase}）"
            
            # 如果异常有安全的错误消息（不包含敏感信息），追加到错误消息中
            safe_msg = ""
            if hasattr(cause, 'args') and cause.args and isinstance(cause.args[0], str):
                safe_msg = str(cause.args[0])[:300]  # 增加长度限制到 300 字符
                # 过滤可能包含敏感信息的关键词
                sensitive_keywords = ['api_key', 'token', 'password', 'secret', 'credential', 'authorization', 'bearer']
                if not any(kw in safe_msg.lower() for kw in sensitive_keywords):
                    # 如果消息不是重复的状态码，则追加
                    if not (status_code and str(status_code) in safe_msg):
                        error_message += f" - {safe_msg}"

            logger.error(
                "Agent run failed: run_id=%s phase=%s error_type=%s status_code=%s detail=%s",
                run.run_id,
                phase,
                error_type,
                status_code or 'N/A',
                safe_msg,
            )
            try:
                self._lifecycle.fail(
                    run.run_id,
                    claim_token,
                    run.execution_attempt,
                    "model_error",
                    error_message,
                    datetime.now(timezone.utc),
                )
            except InvalidRunTransition:
                return
            await self.hub.publish(
                run.run_id,
                "run.failed",
                error_type=type(cause).__name__,
            )
        finally:
            if self._tool_control is not None and waiting_hitl is None:
                await self._tool_control.stop_run(run.run_id)
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
        *,
        resume: Any = None,
    ) -> dict[str, Any]:
        if resume is not None:
            invocation = graph.ainvoke(Command(resume=resume), config=config)
        else:
            invocation = graph.ainvoke(initial, config=config)
        graph_task = asyncio.create_task(invocation)
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
        await self.hub.publish(run.run_id, "run.cancelled")
        return True

    def _wait_for_interrupt(
        self, run: AgentRun, active: ActiveRunContext, result: dict[str, Any]
    ) -> str:
        """分类 interrupt 等待：approval（既有流程）或 clarification（M07 新增）。"""
        values = []
        for item in result.get("__interrupt__", ()) or ():
            value = getattr(item, "value", item)
            if isinstance(value, dict):
                values.append(value)
        kinds = {str(item.get("kind", "approval")) for item in values}
        if "clarification" in kinds:
            request = next((item for item in values if item.get("kind") == "clarification"), {})
            self._wait_for_hitl(run, active)
            asyncio.create_task(
                self.hub.publish(
                    run.run_id,
                    "run.waiting_clarification",
                    question=request.get("question", ""),
                    options=list(request.get("options", ()) or ()),
                    multi_select=bool(request.get("multi_select")),
                )
            )
            return "clarification"
        self._wait_for_hitl(run, active)
        approval_value = next(
            (item for item in values if item.get("approval_id")),
            None,
        )
        asyncio.create_task(
            self.hub.publish(
                run.run_id,
                "run.waiting_approval",
                approval_id=approval_value.get("approval_id") if approval_value else None,
                tool_call_id=approval_value.get("tool_call_id") if approval_value else None,
                tool_id=approval_value.get("tool_id") if approval_value else None,
            )
        )
        return "approval"

    def _wait_for_hitl(self, run: AgentRun, active: ActiveRunContext) -> None:
        try:
            self._lifecycle.wait_approval(
                run.run_id,
                active.claim_token,
                active.execution_attempt,
                datetime.now(timezone.utc),
            )
        except InvalidRunTransition:
            return

    @staticmethod
    def _message_to_dict(message: BaseMessage) -> dict[str, object]:
        return {"type": message.type, "content": message.content}

    @staticmethod
    def _message_from_dict(raw: dict[str, object]) -> BaseMessage:
        kind = raw.get("type")
        content = raw.get("content", "")
        if kind == "system":
            return SystemMessage(content=content)
        if kind == "ai":
            return AIMessage(content=content)
        if kind == "tool":
            return ToolMessage(
                content=content,
                tool_call_id=str(raw.get("tool_call_id", "")),
            )
        return HumanMessage(content=content)

    @staticmethod
    def _memory_outcome_payload(
        outcome: NaturalMemoryOutcome | None,
    ) -> dict[str, object] | None:
        if outcome is None:
            return None
        return {
            "operation": outcome.operation,
            "status": outcome.status,
            "saved_count": outcome.saved_count,
            "rejected_count": outcome.rejected_count,
            "reason_codes": list(outcome.reason_codes),
        }

    @staticmethod
    def _memory_outcome_from_payload(
        payload: object,
    ) -> NaturalMemoryOutcome | None:
        if not isinstance(payload, dict):
            return None
        operation = payload.get("operation")
        status = payload.get("status")
        if not isinstance(operation, str) or not isinstance(status, str):
            return None
        reason_codes = payload.get("reason_codes", ())
        if not isinstance(reason_codes, (list, tuple)):
            reason_codes = ()
        return NaturalMemoryOutcome(
            operation,  # type: ignore[arg-type]
            status,  # type: ignore[arg-type]
            saved_count=int(payload.get("saved_count", 0) or 0),
            rejected_count=int(payload.get("rejected_count", 0) or 0),
            reason_codes=tuple(str(item) for item in reason_codes),
        )

    async def _process_natural_memory_once(
        self,
        history: tuple[Any, ...],
        task_input: TaskInput,
        execution_authorization: Any | None,
    ) -> NaturalMemoryOutcome | None:
        if (
            self._memory is None
            or execution_authorization is None
            or self._memory.natural_intent(task_input.content) is None
        ):
            return None
        try:
            outcome = await asyncio.to_thread(
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
        except Exception as exc:
            logger.warning(
                "Natural memory operation unavailable: phase=memory_extraction "
                "error_type=%s",
                type(exc).__name__,
            )
            return NaturalMemoryOutcome(
                self._memory.natural_intent(task_input.content) or "remember",
                "unavailable",
                reason_codes=("operation_unavailable",),
            )
        if outcome is not None and outcome.status == "unavailable":
            logger.warning(
                "Natural memory operation unavailable: phase=memory_extraction "
                "reason_codes=%s",
                ",".join(outcome.reason_codes) or "unknown",
            )
        return outcome

    async def _build_context_messages(
        self,
        run_id: str,
        history: tuple[Any, ...],
        memory_authorization: Any | None,
        execution_authorization: Any | None,
        task_input: TaskInput,
        natural_outcome: NaturalMemoryOutcome | None = None,
    ) -> tuple[BaseMessage, ...]:
        visible_history = history
        memory_blocks = ()
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
        tool_blocks = (
            self._tool_control.collect_blocks(run_id=run_id)
            if self._tool_control is not None
            else ()
        )
        blocks = ProjectionInputCollector().collect(
            task_content=task_input.content,
            conversation_messages=tuple(
                (item.role, item.content) for item in visible_history
            ),
            additional_blocks=(*memory_blocks, *tool_blocks),
        )
        projected = ContextProjectionService().project(
            FOUNDATION_POLICY, blocks, input_budget=32_000
        )
        return tuple(
            [
                *(SystemMessage(content=item) for item in projected.system_messages),
                *(HumanMessage(content=item) for item in projected.messages),
            ]
        )

    async def _build_planning_mem_prefix(
        self,
        run_id: str,
        history: tuple[Any, ...],
        memory_authorization: Any | None,
        task_input: TaskInput,
    ) -> str:
        """计划层节点共享的记忆/工具状态前缀（每 run 一次装配，对齐 AGI-saber memPrefix）。

        与 _build_context_messages 同源收集（capture_snapshot → summary_blocks /
        context_blocks → tool_control.collect_blocks），只取投影的 system_messages
        段拼接为前缀；conversation 段（placement=messages）不进前缀。降级口径
        与基线一致：任一记忆源超时/异常 → 对应块置空；整体异常 → 返回 ""。
        "" 时四节点 prompt 与 M07 现状完全一致（纯节点内联，零回归）。

        已知小瑕疵：stable-rules 文案「你是 VenAgent 的回答节点」对 planner 角色
        近似适用但非精确；不改 FOUNDATION_POLICY（共享基线，波及面大、收益边际小）。
        """
        memory_blocks = ()
        if self._memory is not None and memory_authorization is not None:
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
            except Exception:
                snapshot = None
            if snapshot is not None:
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
        tool_blocks = (
            self._tool_control.collect_blocks(run_id=run_id)
            if self._tool_control is not None
            else ()
        )
        try:
            blocks = ProjectionInputCollector().collect(
                task_content=task_input.content,
                conversation_messages=(),
                additional_blocks=(*memory_blocks, *tool_blocks),
            )
            projected = ContextProjectionService().project(
                FOUNDATION_POLICY, blocks, input_budget=32_000
            )
        except Exception:
            logger.warning(
                "Planning mem_prefix projection unavailable: run_id=%s", run_id
            )
            return ""
        return "\n\n".join(projected.system_messages)

    def _tool_nodes(
        self,
        run_id: str,
        owner_id: str,
        active: ActiveRunContext,
        history: tuple[Any, ...],
        memory_authorization: Any | None,
        execution_authorization: Any | None,
    ) -> dict[str, Any]:
        async def prepare(state: RunState) -> dict[str, Any]:
            task_input = state.get("task_input")
            if not isinstance(task_input, TaskInput):
                raise RuntimeError("run is missing task input")
            natural_outcome = await self._process_natural_memory_once(
                history,
                task_input,
                execution_authorization,
            )
            return {
                "phase": "synthesizing",
                "natural_memory_outcome": self._memory_outcome_payload(
                    natural_outcome
                ),
            }

        async def model_decision(state: RunState) -> dict[str, Any]:
            task_input = state.get("task_input")
            if not isinstance(task_input, TaskInput):
                raise RuntimeError("run is missing task input")
            
            # 多工具顺序执行：如果队列非空，从队列取下一个工具，不调用模型
            pending_calls = state.get("pending_tool_calls")
            if pending_calls and len(pending_calls) > 0:
                next_call = pending_calls[0]
                remaining = pending_calls[1:] if len(pending_calls) > 1 else None
                return {
                    "phase": "executing",
                    "pending_tool_call": next_call,
                    "pending_tool_calls": remaining,
                    "tool_observation": None,
                }
            
            messages = await self._build_context_messages(
                run_id,
                history,
                memory_authorization,
                execution_authorization,
                task_input,
                self._memory_outcome_from_payload(
                    state.get("natural_memory_outcome")
                ),
            )
            natural_memory_request = (
                self._memory is not None
                and self._memory.natural_intent(task_input.content) is not None
            )
            tool_schemas = (
                ()
                if natural_memory_request
                else (
                    self._tool_control.model_tools(run_id)
                    if self._tool_control is not None
                    else ()
                )
            )
            stream_model = self._model
            try:
                if tool_schemas and hasattr(self._model, "bind_tools") and callable(
                    getattr(self._model, "bind_tools", None)
                ):
                    stream_model = self._model.bind_tools(tool_schemas)
                elif tool_schemas:
                    await self.hub.publish(
                        run_id,
                        "tool.event",
                        kind="model_tool_calling_unsupported",
                        reason="provider_does_not_support_bind_tools",
                    )
            except Exception as exc:
                raise ModelPhaseError("model_decision", exc) from exc
            parts: list[str] = []
            assembler = AssistantBlockAssembler()
            chunks: list[Any] = []
            output_bytes = 0
            try:
                async for chunk in self._stream_model(messages, model=stream_model):
                    if active.token.is_cancelled():
                        raise RunCancelled
                    chunks.append(chunk)
                    for block_type, delta in normalize_assistant_chunk(chunk):
                        delta_bytes = len(delta.encode("utf-8"))
                        if output_bytes + delta_bytes > MAX_STREAM_OUTPUT_BYTES:
                            raise OutputLimitExceeded
                        output_bytes += delta_bytes
                        if block_type == "text":
                            parts.append(delta)
                        for normalized in assembler.push(block_type, delta):
                            await self.hub.publish(
                                run_id,
                                "assistant.chunk",
                                execution_attempt=active.execution_attempt,
                                chunk=normalized,
                            )
            except (RunCancelled, OutputLimitExceeded):
                raise
            except Exception as exc:
                raise ModelPhaseError("model_decision", exc) from exc
            for normalized in assembler.finish():
                await self.hub.publish(
                    run_id,
                    "assistant.chunk",
                    execution_attempt=active.execution_attempt,
                    chunk=normalized,
                )
            try:
                tool_calls = model_tool_calls_from_chunks(tuple(chunks))
            except ModelToolCallInvalid:
                # 诊断插桩：留下 provider 原始工具调用分片形态，定位解析兼容性。
                for i, c in enumerate(chunks):
                    tcc = getattr(c, "tool_call_chunks", None)
                    tc = getattr(c, "tool_calls", None)
                    if tcc or tc:
                        logger.warning(
                            "tool call chunk dump idx=%s tool_call_chunks=%r tool_calls=%r",
                            i,
                            str(tcc)[:300],
                            str(tc)[:300],
                        )
                raise
            if tool_calls:
                # 多工具顺序执行：取第一个，其余放入队列
                call = tool_calls[0]
                staged = self._tool_control.stage_tool_call(
                    run_id, owner_id, call
                )
                pending_calls = None
                if len(tool_calls) > 1:
                    # 将后续工具调用暂存为 pending_tool_calls
                    remaining = []
                    for c in tool_calls[1:]:
                        stage_result = self._tool_control.stage_tool_call(
                            run_id, owner_id, c
                        )
                        remaining.append(
                            PendingToolCallRef(
                                tool_call_id=c.id,
                                operation_key=stage_result.operation_key,
                                tool_id=c.name,
                            )
                        )
                    pending_calls = tuple(remaining)
                return {
                    "phase": "executing",
                    "pending_tool_call": PendingToolCallRef(
                        tool_call_id=call.id,
                        operation_key=staged.operation_key,
                        tool_id=call.name,
                    ),
                    "pending_tool_calls": pending_calls,
                    "tool_observation": None,
                }
            content = "".join(parts)
            if not content:
                raise RuntimeError("model returned no text")
            return {
                "phase": "synthesizing",
                "final_answer": FinalAnswer(content, blocks=assembler.blocks),
                "failure": None,
                "pending_tool_call": None,
                "tool_observation": None,
            }

        async def execute_tool(state: RunState) -> dict[str, Any]:
            pending = state.get("pending_tool_call")
            if pending is None:
                raise RuntimeError("execute_tool requires pending_tool_call")
            result = await self._tool_control.resume_tool(
                run_id, owner_id, pending, cancel_event=active.token
            )
            while result.status == "awaiting_approval":
                interrupt(
                    {
                        "kind": "approval",
                        "approval_id": result.approval_id,
                        "run_id": run_id,
                        "tool_id": pending.tool_id,
                        "tool_call_id": pending.tool_call_id,
                    }
                )
                result = await self._tool_control.resume_tool(
                    run_id, owner_id, pending, cancel_event=active.token
                )
            return {
                "phase": "synthesizing",
                "tool_observation": ToolObservationRef(
                    tool_call_id=result.tool_call_id or pending.tool_call_id,
                    operation_id=result.operation_id,
                    status=result.status,
                    summary=result.summary,
                    approval_id=result.approval_id or pending.approval_id,
                ),
                "pending_tool_call": pending,
            }

        async def model_finalize(state: RunState) -> dict[str, Any]:
            task_input = state.get("task_input")
            if not isinstance(task_input, TaskInput):
                raise RuntimeError("run is missing task input")
            messages: list[BaseMessage] = list(
                await self._build_context_messages(
                    run_id,
                    history,
                    memory_authorization,
                    execution_authorization,
                    task_input,
                    self._memory_outcome_from_payload(
                        state.get("natural_memory_outcome")
                    ),
                )
            )
            observation = state.get("tool_observation")
            pending = state.get("pending_tool_call")
            pending_calls = state.get("pending_tool_calls")
            executed = state.get("executed_tool_observations") or ()
            
            # 重建所有已执行工具的消息历史
            for exec_pending, exec_observation in executed:
                arguments = self._tool_control.load_tool_arguments(
                    run_id, owner_id, exec_pending
                )
                messages.append(
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "id": exec_pending.tool_call_id,
                                "name": exec_pending.tool_id,
                                "args": arguments,
                                "type": exec_pending.call_type,
                            }
                        ],
                    )
                )
                messages.append(
                    ToolMessage(
                        content=self._tool_control.project_tool_result(
                            run_id, owner_id, exec_pending, exec_observation
                        ),
                        tool_call_id=exec_pending.tool_call_id,
                    )
                )
            
            # 构建当前工具调用和结果的消息
            if pending is not None and observation is not None:
                arguments = self._tool_control.load_tool_arguments(
                    run_id, owner_id, pending
                )
                messages.append(
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "id": pending.tool_call_id,
                                "name": pending.tool_id,
                                "args": arguments,
                                "type": pending.call_type,
                            }
                        ],
                    )
                )
                messages.append(
                    ToolMessage(
                        content=self._tool_control.project_tool_result(
                            run_id, owner_id, pending, observation
                        ),
                        tool_call_id=pending.tool_call_id,
                    )
                )
            
            # 如果还有待执行的工具，保存当前工具结果到历史，回 model_decision 取下一个
            if pending_calls and len(pending_calls) > 0:
                # 保存当前工具的 observation 到历史中
                executed = state.get("executed_tool_observations") or ()
                if pending is not None and observation is not None:
                    executed = executed + ((pending, observation),)
                
                # 返回到 model_decision，由它从队列取下一个工具
                return {
                    "phase": "selecting_tools",
                    "tool_observation": None,
                    "executed_tool_observations": executed,
                }
            
            # 所有工具执行完毕，调用模型生成最终答案
            parts: list[str] = []
            assembler = AssistantBlockAssembler()
            chunks: list[Any] = []
            output_bytes = 0
            try:
                async for chunk in self._stream_model(messages):
                    if active.token.is_cancelled():
                        raise RunCancelled
                    chunks.append(chunk)
                    for block_type, delta in normalize_assistant_chunk(chunk):
                        delta_bytes = len(delta.encode("utf-8"))
                        if output_bytes + delta_bytes > MAX_STREAM_OUTPUT_BYTES:
                            raise OutputLimitExceeded
                        output_bytes += delta_bytes
                        if block_type == "text":
                            parts.append(delta)
                        for normalized in assembler.push(block_type, delta):
                            await self.hub.publish(
                                run_id,
                                "assistant.chunk",
                                execution_attempt=active.execution_attempt,
                                chunk=normalized,
                            )
            except (RunCancelled, OutputLimitExceeded):
                raise
            except Exception as exc:
                raise ModelPhaseError("model_finalize", exc) from exc
            for normalized in assembler.finish():
                await self.hub.publish(
                    run_id,
                    "assistant.chunk",
                    execution_attempt=active.execution_attempt,
                    chunk=normalized,
                )
            if model_tool_calls_from_chunks(tuple(chunks)):
                raise RuntimeError("model returned tool call during finalize")
            content = "".join(parts)
            if not content:
                raise RuntimeError("model returned no text")
            return {
                "phase": "synthesizing",
                "final_answer": FinalAnswer(content, blocks=assembler.blocks),
                "failure": None,
                "tool_observation": None,
            }

        async def final(state: RunState) -> dict[str, Any]:
            return {}

        return {
            "prepare": prepare,
            "model_decision": model_decision,
            "execute_tool": execute_tool,
            "model_finalize": model_finalize,
            "final": final,
        }

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
            tool_blocks = (
                self._tool_control.collect_blocks(run_id=run_id)
                if self._tool_control is not None
                else ()
            )
            blocks = ProjectionInputCollector().collect(
                task_content=task_input.content,
                conversation_messages=tuple(
                    (item.role, item.content) for item in visible_history
                ),
                additional_blocks=(*memory_blocks, *tool_blocks),
            )
            projected = ContextProjectionService().project(
                FOUNDATION_POLICY, blocks, input_budget=32_000
            )
            messages: list[BaseMessage] = [
                *(SystemMessage(content=item) for item in projected.system_messages),
                *(HumanMessage(content=item) for item in projected.messages),
            ]
            parts: list[str] = []
            assembler = AssistantBlockAssembler()
            output_bytes = 0
            async for chunk in self._stream_model(messages):
                if active.token.is_cancelled():
                    raise RunCancelled
                for block_type, delta in normalize_assistant_chunk(chunk):
                    delta_bytes = len(delta.encode("utf-8"))
                    if output_bytes + delta_bytes > MAX_STREAM_OUTPUT_BYTES:
                        raise OutputLimitExceeded
                    output_bytes += delta_bytes
                    if block_type == "text":
                        parts.append(delta)
                    for normalized in assembler.push(block_type, delta):
                        await self.hub.publish(
                            run_id,
                            "assistant.chunk",
                            execution_attempt=active.execution_attempt,
                            chunk=normalized,
                        )
            for normalized in assembler.finish():
                await self.hub.publish(
                    run_id,
                    "assistant.chunk",
                    execution_attempt=active.execution_attempt,
                    chunk=normalized,
                )
            content = "".join(parts)
            if not content:
                raise RuntimeError("model returned no text")
            return {
                "phase": "synthesizing",
                "final_answer": FinalAnswer(content, blocks=assembler.blocks),
                "failure": None,
            }

        return answer

    async def _stream_model(
        self,
        messages: Sequence[BaseMessage],
        *,
        model: Any | None = None,
    ) -> AsyncIterator[Any]:
        target = model if model is not None else self._model
        async_stream = getattr(target, "astream", None)
        if callable(async_stream):
            async for chunk in async_stream(messages):
                yield chunk
            return
        stream = getattr(target, "stream", None)
        if callable(stream):
            iterator = iter(stream(messages))
            while True:
                chunk = await asyncio.to_thread(_next_or_end, iterator)
                if chunk is _STREAM_END:
                    return
                yield chunk
        else:
            yield await asyncio.to_thread(target.invoke, messages)

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
