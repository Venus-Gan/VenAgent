"""确定性 `/memory` 命令 adapter。"""

from __future__ import annotations

from dataclasses import dataclass

from ..ownership.models import Actor
from .errors import MemoryError, MemoryInvalidCommand
from .ports import MemoryStoreError as StoreError
from .service import MemoryService


@dataclass(frozen=True)
class MemoryCommandResult:
    code: str
    message: str


class MemoryCommandAdapter:
    def __init__(self, service: MemoryService) -> None:
        self._service = service

    @staticmethod
    def matches(content: str) -> bool:
        return content.strip() == "/memory" or content.lstrip().startswith("/memory ")

    def execute(self, actor: Actor, content: str) -> MemoryCommandResult:
        try:
            return self._execute(actor, content)
        except MemoryError as exc:
            return _error_result(exc)
        except StoreError:
            return MemoryCommandResult(
                "memory_persistence_unavailable",
                "记忆权威存储暂时不可用，操作未确认成功。",
            )

    def _execute(self, actor: Actor, content: str) -> MemoryCommandResult:
        parts = content.strip().split()
        if not parts or parts[0] != "/memory":
            raise MemoryInvalidCommand
        operation = parts[1] if len(parts) > 1 else "help"
        auth = self._service.command_authorization(
            actor, action="write" if operation == "update" else "manage"
        )
        if operation == "help" and len(parts) in {1, 2}:
            return MemoryCommandResult(
                "memory_help",
                "可用命令：/memory status|list [cursor]|show <id>|update <id> <fact>|forget <id>|revoke-source <source_ref>|disable|enable|delete-all CONFIRM",
            )
        if operation == "status" and len(parts) == 2:
            status = self._service.status(auth)
            return MemoryCommandResult(
                "memory_status",
                f"记忆状态：{status.state}（{status.reason_code}）；待处理 {status.pending}，失败 {status.failed}，事实索引待同步 {status.index_pending}，G1 图待同步 {status.graph_pending}，G1 图失败 {status.graph_failed}。"
                + (
                    f" 安全错误摘要：{status.error_summary}。"
                    if status.error_summary
                    else ""
                ),
            )
        if operation == "list" and len(parts) in {2, 3}:
            page = self._service.list(auth, parts[2] if len(parts) == 3 else None)
            if not page.items:
                return MemoryCommandResult("memory_list", "没有活动长期记忆。")
            lines = [f"{item.memory_id}  {item.fact[:80]}" for item in page.items]
            if page.next_cursor:
                lines.append(f"下一页：/memory list {page.next_cursor}")
            return MemoryCommandResult("memory_list", "\n".join(lines))
        if operation == "show" and len(parts) == 3:
            fact = self._service.show(auth, parts[2])
            sources = "、".join(fact.source_refs) or "无"
            valid_until = (
                fact.valid_until.isoformat() if fact.valid_until else "长期有效"
            )
            return MemoryCommandResult(
                "memory_show",
                f"{fact.memory_id}\n事实：{fact.fact}\n状态：{fact.status}\n事实可用：是\nG1 图待同步：{self._service.status(auth).graph_pending}\n有效期：{valid_until}\n来源：{sources}",
            )
        if operation == "forget" and len(parts) == 3:
            self._service.forget(auth, parts[2])
            return MemoryCommandResult("memory_forgotten", "该记忆已不可召回。")
        if operation == "update" and len(parts) >= 4:
            fact = self._service.update(auth, parts[2], " ".join(parts[3:]))
            status = self._service.status(
                self._service.command_authorization(actor, action="manage")
            )
            suffix = (
                "；事实已可用，G1 图正在后台同步。"
                if status.graph_pending
                else "。"
            )
            return MemoryCommandResult(
                "memory_updated", f"记忆已更新，新 ID：{fact.memory_id}{suffix}"
            )
        if operation == "revoke-source" and len(parts) == 3:
            count, token = self._service.request_revoke_source(auth, parts[2])
            if token is not None:
                return MemoryCommandResult(
                    "memory_source_confirmation_required",
                    f"该来源影响 {count} 条活动记忆。确认撤销：/memory revoke-source {parts[2]} {token}",
                )
            return MemoryCommandResult(
                "memory_source_revoked", f"来源已撤销，{count} 条记忆受到影响。"
            )
        if operation == "revoke-source" and len(parts) == 4:
            count = self._service.confirm_revoke_source(auth, parts[2], parts[3])
            return MemoryCommandResult(
                "memory_source_revoked", f"来源已撤销，{count} 条记忆受到影响。"
            )
        if operation == "disable" and len(parts) == 2:
            self._service.set_enabled(auth, False)
            return MemoryCommandResult(
                "memory_disabled", "记忆已关闭，现有数据未删除。"
            )
        if operation == "enable" and len(parts) == 2:
            self._service.set_enabled(auth, True)
            return MemoryCommandResult("memory_enabled", "记忆已启用。")
        if operation == "delete-all" and len(parts) == 2:
            token, count = self._service.request_delete_all(auth)
            return MemoryCommandResult(
                "memory_delete_confirmation_required",
                f"将删除 {count} 条活动记忆。5 分钟内确认：/memory delete-all {token}",
            )
        if operation == "delete-all" and len(parts) == 3:
            count = self._service.confirm_delete_all(auth, parts[2])
            return MemoryCommandResult(
                "memory_all_deleted", f"全部活动记忆已不可召回，共 {count} 条。"
            )
        raise MemoryInvalidCommand


def _error_result(exc: MemoryError) -> MemoryCommandResult:
    messages = {
        "memory_unauthorized": "当前身份或授权已失效，未执行记忆操作。",
        "memory_disabled": "记忆已关闭，写入未执行。",
        "memory_unsupported": "当前临时身份不支持跨会话记忆。",
        "memory_not_found": "未找到当前账号可管理的活动记忆。",
        "memory_invalid_cursor": "分页游标无效或不属于当前账号。",
        "memory_unsafe_content": "该内容不符合长期事实的持久化规则，未写入。",
        "memory_invalid_command": "命令格式无效，请使用 /memory help 查看可用命令。",
        "memory_confirmation_invalid": "确认 token 无效、已过期、已使用或数据状态已变化，未执行操作。",
        "memory_purge_pending": "记忆仍在完成删除清理，当前不能重新启用。",
        "memory_disable_not_persisted": "当前进程已停止记忆注入，但全局关闭未能持久化，请稍后重试。",
    }
    return MemoryCommandResult(exc.code, messages.get(exc.code, "记忆操作失败。"))
