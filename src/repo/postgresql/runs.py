"""PostgreSQL AgentRun adapter：幂等创建、租约 claim 与 fencing。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from hashlib import sha256
from typing import Any
from uuid import uuid4

from ...agent.events import RunEvent
from ...agent.graph import RUNTIME_CONTRACT_VERSION
from ...agent.ports import RunStoreError as StoreError
from ...agent.runs import (
    AgentRun,
    InvalidRunTransition,
    RunAuthorizationInvalid,
    RunNotFound,
)
from ...conversation.errors import (
    ConversationBusy,
    ConversationDeleting,
    ConversationNotFound,
    IdempotencyConflict,
    RetryNotAllowed,
)
from ...conversation.models import RunCreation
from ...conversation.rules import automatic_title
from ...ownership.models import Actor, ExecutionAuthorization
from .conversation_mapping import (
    agent_run_from_row,
    message_from_row,
    run_event_from_row,
)


class _PostgresRunMixin:
    def append_run_event(
        self, run_id: str, event_type: str, payload: dict, now: datetime
    ) -> RunEvent:
        try:
            with self._pool.connection() as conn, conn.transaction():
                locked = conn.execute(
                    "SELECT run_id FROM agent_runs WHERE run_id=%s FOR UPDATE",
                    (run_id,),
                ).fetchone()
                if locked is None:
                    raise RunNotFound
                row = conn.execute(
                    """INSERT INTO run_events
                    (run_id,sequence,event_type,payload,created_at)
                    SELECT %s,COALESCE(max(sequence),0)+1,%s,%s::jsonb,%s
                    FROM run_events WHERE run_id=%s RETURNING *""",
                    (run_id, event_type, json.dumps(payload), now, run_id),
                ).fetchone()
            return run_event_from_row(row)
        except RunNotFound:
            raise
        except Exception as exc:
            raise StoreError("unable to append run event") from exc

    def run_events(
        self, owner_id: str, run_id: str, *, after_sequence: int = 0
    ) -> tuple[RunEvent, ...]:
        try:
            with self._pool.connection() as conn:
                rows = conn.execute(
                    """SELECT event.* FROM run_events event
                    JOIN agent_runs run USING (run_id)
                    WHERE event.run_id=%s AND run.owner_id=%s AND event.sequence>%s
                    ORDER BY event.sequence""",
                    (run_id, owner_id, after_sequence),
                ).fetchall()
                if not rows and conn.execute(
                    "SELECT 1 FROM agent_runs WHERE run_id=%s AND owner_id=%s",
                    (run_id, owner_id),
                ).fetchone() is None:
                    raise RunNotFound
            return tuple(run_event_from_row(row) for row in rows)
        except RunNotFound:
            raise
        except Exception as exc:
            raise StoreError("unable to read run events") from exc

    def create_run(
        self,
        actor: Actor,
        conversation_id: str,
        message: str,
        client_request_id: str,
        now: datetime,
    ) -> RunCreation:
        payload_hash = sha256(message.encode("utf-8")).hexdigest()
        try:
            with self._pool.connection() as conn, conn.transaction():
                self._lock_active_conversation(conn, actor.owner_id, conversation_id)
                replay = self._request_replay(
                    conn, conversation_id, client_request_id, "create", payload_hash
                )
                if replay is not None:
                    return replay
                self._require_no_active_run(conn, conversation_id)
                message_id, run_id, grant_id = str(uuid4()), str(uuid4()), str(uuid4())
                sequence = self._next_sequence(conn, conversation_id)
                input_row = conn.execute(
                    """INSERT INTO conversation_messages
                    (message_id,conversation_id,owner_id,role,content,sequence,client_request_id,created_at)
                    VALUES (%s,%s,%s,'user',%s,%s,%s,%s) RETURNING *""",
                    (
                        message_id,
                        conversation_id,
                        actor.owner_id,
                        message,
                        sequence,
                        client_request_id,
                        now,
                    ),
                ).fetchone()
                self._insert_grant(conn, grant_id, run_id, actor, conversation_id, now)
                run_row = self._insert_run(
                    conn,
                    run_id,
                    conversation_id,
                    actor.owner_id,
                    message_id,
                    grant_id,
                    now,
                )
                conn.execute(
                    """INSERT INTO run_requests
                    (conversation_id,client_request_id,operation,payload_hash,input_message_id,run_id)
                    VALUES (%s,%s,'create',%s,%s,%s)""",
                    (
                        conversation_id,
                        client_request_id,
                        payload_hash,
                        message_id,
                        run_id,
                    ),
                )
                conn.execute(
                    "UPDATE conversations SET updated_at=%s WHERE conversation_id=%s",
                    (now, conversation_id),
                )
            return RunCreation(agent_run_from_row(run_row), message_from_row(input_row))
        except (
            ConversationNotFound,
            ConversationDeleting,
            ConversationBusy,
            IdempotencyConflict,
        ):
            raise
        except Exception as exc:
            raise StoreError("unable to create agent run") from exc

    def retry_run(
        self, actor: Actor, source_run_id: str, client_request_id: str, now: datetime
    ) -> RunCreation:
        try:
            with self._pool.connection() as conn, conn.transaction():
                source = conn.execute(
                    "SELECT * FROM agent_runs WHERE run_id=%s AND owner_id=%s FOR UPDATE",
                    (source_run_id, actor.owner_id),
                ).fetchone()
                if source is None:
                    raise RunNotFound
                if str(source["status"]) not in {"failed", "cancelled", "incompatible"}:
                    raise RetryNotAllowed
                conversation_id = str(source["conversation_id"])
                self._lock_active_conversation(conn, actor.owner_id, conversation_id)
                replay = self._request_replay(
                    conn, conversation_id, client_request_id, "retry", "0" * 64
                )
                if replay is not None:
                    return replay
                latest = conn.execute(
                    "SELECT message_id FROM conversation_messages WHERE conversation_id=%s AND role='user' ORDER BY sequence DESC LIMIT 1",
                    (conversation_id,),
                ).fetchone()
                if latest is None or str(latest["message_id"]) != str(
                    source["input_message_id"]
                ):
                    raise RetryNotAllowed
                self._require_no_active_run(conn, conversation_id)
                run_id, grant_id = str(uuid4()), str(uuid4())
                self._insert_grant(conn, grant_id, run_id, actor, conversation_id, now)
                run_row = self._insert_run(
                    conn,
                    run_id,
                    conversation_id,
                    actor.owner_id,
                    str(source["input_message_id"]),
                    grant_id,
                    now,
                    retry_of_run_id=source_run_id,
                )
                conn.execute(
                    """INSERT INTO run_requests
                    (conversation_id,client_request_id,operation,payload_hash,input_message_id,run_id)
                    VALUES (%s,%s,'retry',%s,%s,%s)""",
                    (
                        conversation_id,
                        client_request_id,
                        "0" * 64,
                        source["input_message_id"],
                        run_id,
                    ),
                )
                input_row = conn.execute(
                    "SELECT * FROM conversation_messages WHERE message_id=%s",
                    (source["input_message_id"],),
                ).fetchone()
            return RunCreation(agent_run_from_row(run_row), message_from_row(input_row))
        except (
            RunNotFound,
            RetryNotAllowed,
            ConversationNotFound,
            ConversationDeleting,
            ConversationBusy,
            IdempotencyConflict,
        ):
            raise
        except Exception as exc:
            raise StoreError("unable to retry agent run") from exc

    def get_run(self, owner_id: str, run_id: str) -> AgentRun | None:
        try:
            with self._pool.connection() as conn:
                row = conn.execute(
                    "SELECT * FROM agent_runs WHERE owner_id=%s AND run_id=%s",
                    (owner_id, run_id),
                ).fetchone()
            return None if row is None else agent_run_from_row(row)
        except Exception as exc:
            raise StoreError("unable to read agent run") from exc

    def get_run_internal(self, run_id: str) -> AgentRun | None:
        try:
            with self._pool.connection() as conn:
                row = conn.execute(
                    "SELECT * FROM agent_runs WHERE run_id=%s", (run_id,)
                ).fetchone()
            return None if row is None else agent_run_from_row(row)
        except Exception as exc:
            raise StoreError("unable to read agent run") from exc

    def authorize_run(self, run_id: str, now: datetime) -> ExecutionAuthorization:
        try:
            with self._pool.connection() as conn:
                row = conn.execute(
                    """SELECT run.*,run_grant.allowed_data_scopes,run_grant.allowed_action_classes,
                    run_grant.tenant_id,run_grant.authorization_epoch,
                    run_grant.revoked_at AS grant_revoked_at,
                    run_grant.expires_at AS grant_expires_at,owner.lifecycle_state,
                    owner.authorization_epoch AS owner_epoch
                    FROM agent_runs run JOIN run_grants run_grant
                    ON run_grant.grant_id=run.grant_id
                    JOIN owners owner ON owner.owner_id=run.owner_id WHERE run.run_id=%s""",
                    (run_id,),
                ).fetchone()
            if row is None:
                raise RunNotFound
            if (
                row["grant_revoked_at"] is not None
                or row["grant_expires_at"] <= now
                or row["lifecycle_state"] != "active"
                or int(row["authorization_epoch"]) != int(row["owner_epoch"])
            ):
                raise RunAuthorizationInvalid
            scopes = tuple(
                json.loads(row["allowed_data_scopes"])
                if isinstance(row["allowed_data_scopes"], str)
                else row["allowed_data_scopes"]
            )
            actions = tuple(
                json.loads(row["allowed_action_classes"])
                if isinstance(row["allowed_action_classes"], str)
                else row["allowed_action_classes"]
            )
            return ExecutionAuthorization(
                str(row["run_id"]),
                str(row["owner_id"]),
                str(row["tenant_id"]),
                str(row["conversation_id"]),
                scopes,
                actions,
                int(row["authorization_epoch"]),
            )
        except (RunNotFound, RunAuthorizationInvalid):
            raise
        except Exception as exc:
            raise StoreError("unable to authorize agent run") from exc

    def claim_next(
        self, worker_id: str, now: datetime, lease_duration: timedelta
    ) -> AgentRun | None:
        try:
            with self._pool.connection() as conn, conn.transaction():
                row = conn.execute(
                    """SELECT run.* FROM agent_runs run
                    WHERE (run.status='queued' OR (run.status='running' AND run.lease_expires_at<=%s))
                    AND (SELECT count(*) FROM agent_runs active WHERE active.owner_id=run.owner_id
                         AND active.status='running' AND active.lease_expires_at>%s)<2
                    ORDER BY run.created_at,run.run_id FOR UPDATE SKIP LOCKED LIMIT 1""",
                    (now, now),
                ).fetchone()
                if row is None:
                    return None
                updated = conn.execute(
                    """UPDATE agent_runs SET status='running',started_at=COALESCE(started_at,%s),
                    updated_at=%s,claimed_by=%s,claim_token=%s,lease_expires_at=%s,
                    execution_attempt=execution_attempt+1,phase=COALESCE(phase,'synthesizing')
                    WHERE run_id=%s RETURNING *""",
                    (
                        now,
                        now,
                        worker_id,
                        str(uuid4()),
                        now + lease_duration,
                        row["run_id"],
                    ),
                ).fetchone()
            return agent_run_from_row(updated)
        except Exception as exc:
            raise StoreError("unable to claim agent run") from exc

    def heartbeat(
        self,
        run_id: str,
        worker_id: str,
        claim_token: str,
        execution_attempt: int,
        now: datetime,
        lease_duration: timedelta,
    ) -> AgentRun:
        try:
            with self._pool.connection() as conn:
                row = conn.execute(
                    """UPDATE agent_runs SET updated_at=%s,lease_expires_at=%s
                    WHERE run_id=%s AND status='running' AND claimed_by=%s AND claim_token=%s AND execution_attempt=%s
                    RETURNING *""",
                    (
                        now,
                        now + lease_duration,
                        run_id,
                        worker_id,
                        claim_token,
                        execution_attempt,
                    ),
                ).fetchone()
            if row is None:
                raise InvalidRunTransition("stale or invalid run claim")
            return agent_run_from_row(row)
        except InvalidRunTransition:
            raise
        except Exception as exc:
            raise StoreError("unable to heartbeat agent run") from exc

    def request_cancel(self, owner_id: str, run_id: str, now: datetime) -> AgentRun:
        try:
            with self._pool.connection() as conn:
                row = conn.execute(
                    """UPDATE agent_runs SET cancel_requested_at=COALESCE(cancel_requested_at,%s),updated_at=%s
                    WHERE owner_id=%s AND run_id=%s AND status IN ('queued','running','waiting_approval') RETURNING *""",
                    (now, now, owner_id, run_id),
                ).fetchone()
                if row is None:
                    row = conn.execute(
                        "SELECT * FROM agent_runs WHERE owner_id=%s AND run_id=%s",
                        (owner_id, run_id),
                    ).fetchone()
            if row is None:
                raise RunNotFound
            return agent_run_from_row(row)
        except RunNotFound:
            raise
        except Exception as exc:
            raise StoreError("unable to request run cancellation") from exc

    def wait_approval_run(
        self,
        run_id: str,
        claim_token: str,
        execution_attempt: int,
        now: datetime,
    ) -> AgentRun:
        try:
            with self._pool.connection() as conn:
                row = conn.execute(
                    """UPDATE agent_runs
                    SET status='waiting_approval',updated_at=%s,phase='awaiting_approval',
                    claimed_by=NULL,claim_token=NULL,lease_expires_at=NULL
                    WHERE run_id=%s AND status='running' AND claim_token=%s AND execution_attempt=%s
                    RETURNING *""",
                    (now, run_id, claim_token, execution_attempt),
                ).fetchone()
            if row is None:
                raise InvalidRunTransition("stale or invalid run claim")
            return agent_run_from_row(row)
        except InvalidRunTransition:
            raise
        except Exception as exc:
            raise StoreError("unable to wait for approval") from exc

    def resume_run(self, run_id: str, now: datetime) -> AgentRun:
        try:
            with self._pool.connection() as conn, conn.transaction():
                row = conn.execute(
                    """UPDATE agent_runs
                    SET status='queued',updated_at=%s,phase='synthesizing'
                    WHERE run_id=%s AND status='waiting_approval' RETURNING *""",
                    (now, run_id),
                ).fetchone()
                if row is not None:
                    return agent_run_from_row(row)
                current = conn.execute(
                    "SELECT status FROM agent_runs WHERE run_id=%s FOR UPDATE",
                    (run_id,),
                ).fetchone()
                if current is None:
                    raise RunNotFound
                status = str(current["status"])
                if status in {"cancelled", "succeeded", "failed", "incompatible"}:
                    raise InvalidRunTransition("run_terminal")
                if status in {"queued", "running"}:
                    raise InvalidRunTransition("run_already_resumed")
                raise InvalidRunTransition("run_not_waiting_approval")
        except (RunNotFound, InvalidRunTransition):
            raise
        except Exception as exc:
            raise StoreError("unable to resume agent run") from exc

    def cancel_waiting_approval(
        self,
        owner_id: str,
        run_id: str,
        now: datetime,
    ) -> AgentRun:
        try:
            with self._pool.connection() as conn, conn.transaction():
                row = conn.execute(
                    """UPDATE agent_runs
                    SET status='cancelled',completed_at=%s,updated_at=%s,
                    terminal_reason_code='user_cancelled',terminal_message='运行已取消',
                    claimed_by=NULL,claim_token=NULL,lease_expires_at=NULL
                    WHERE run_id=%s AND owner_id=%s AND status='waiting_approval'
                    RETURNING *""",
                    (now, now, run_id, owner_id),
                ).fetchone()
                if row is None:
                    existing = conn.execute(
                        "SELECT * FROM agent_runs WHERE run_id=%s AND owner_id=%s",
                        (run_id, owner_id),
                    ).fetchone()
                    if existing is None:
                        raise RunNotFound
                    if str(existing["status"]) == "cancelled":
                        return agent_run_from_row(existing)
                    raise InvalidRunTransition("run is not waiting for approval")
            return agent_run_from_row(row)
        except (RunNotFound, InvalidRunTransition):
            raise
        except Exception as exc:
            raise StoreError("unable to cancel waiting approval run") from exc

    def set_run_skill(
        self,
        owner_id: str,
        run_id: str,
        skill_id: str | None,
        skill_name: str | None,
        now: datetime,
    ) -> AgentRun:
        try:
            with self._pool.connection() as conn:
                row = conn.execute(
                    """UPDATE agent_runs
                    SET selected_skill_id=%s, selected_skill_name=%s, updated_at=%s
                    WHERE owner_id=%s AND run_id=%s RETURNING *""",
                    (skill_id, skill_name, now, owner_id, run_id),
                ).fetchone()
            if row is None:
                raise RunNotFound
            return agent_run_from_row(row)
        except RunNotFound:
            raise
        except Exception as exc:
            raise StoreError("unable to set run skill") from exc

    def succeed_run(
        self,
        run_id: str,
        claim_token: str,
        execution_attempt: int,
        answer: str,
        now: datetime,
        blocks: tuple[dict[str, str], ...] = (),
    ) -> AgentRun:
        try:
            with self._pool.connection() as conn, conn.transaction():
                run = self._lock_claim(conn, run_id, claim_token, execution_attempt)
                if str(run["status"]) == "succeeded":
                    return agent_run_from_row(run)
                if run["cancel_requested_at"] is not None:
                    raise InvalidRunTransition(
                        "cancel was requested before finalization"
                    )
                conversation = self._lock_active_conversation(
                    conn, str(run["owner_id"]), str(run["conversation_id"])
                )
                prior = conn.execute(
                    "SELECT * FROM conversation_messages WHERE source_run_id=%s OR reply_to_message_id=%s",
                    (run_id, run["input_message_id"]),
                ).fetchone()
                if prior is None:
                    output_id = str(uuid4())
                    output = conn.execute(
                        """INSERT INTO conversation_messages
                    (message_id,conversation_id,owner_id,role,content,content_blocks,sequence,source_run_id,reply_to_message_id,created_at)
                    VALUES (%s,%s,%s,'assistant',%s,%s::jsonb,%s,%s,%s,%s) RETURNING *""",
                        (
                            output_id,
                            run["conversation_id"],
                            run["owner_id"],
                            answer,
                            json.dumps(blocks),
                            self._next_sequence(conn, str(run["conversation_id"])),
                            run_id,
                            run["input_message_id"],
                            now,
                        ),
                    ).fetchone()
                else:
                    output = prior
                title = conversation["title"]
                if (
                    conversation["title_source"] == "auto"
                    and conn.execute(
                        "SELECT count(*) AS count FROM conversation_messages WHERE conversation_id=%s AND role='assistant' AND message_id<>%s",
                        (run["conversation_id"], output["message_id"]),
                    ).fetchone()["count"]
                    == 0
                ):
                    source = conn.execute(
                        "SELECT content FROM conversation_messages WHERE message_id=%s",
                        (run["input_message_id"],),
                    ).fetchone()
                    title = automatic_title(str(source["content"]))
                conn.execute(
                    "UPDATE conversations SET title=%s,updated_at=%s,last_successful_at=%s WHERE conversation_id=%s",
                    (title, now, now, run["conversation_id"]),
                )
                row = conn.execute(
                    """UPDATE agent_runs SET status='succeeded',output_message_id=%s,completed_at=%s,updated_at=%s,completed_nodes=total_nodes,terminal_reason_code=NULL,terminal_message=NULL,claimed_by=NULL,claim_token=NULL,lease_expires_at=NULL WHERE run_id=%s RETURNING *""",
                    (output["message_id"], now, now, run_id),
                ).fetchone()
            return agent_run_from_row(row)
        except (
            RunNotFound,
            InvalidRunTransition,
            ConversationNotFound,
            ConversationDeleting,
        ):
            raise
        except Exception as exc:
            raise StoreError("unable to finalize agent run") from exc

    def fail_run(
        self,
        run_id: str,
        claim_token: str,
        execution_attempt: int,
        reason_code: str,
        message: str,
        now: datetime,
    ) -> AgentRun:
        try:
            with self._pool.connection() as conn, conn.transaction():
                run = self._lock_claim(conn, run_id, claim_token, execution_attempt)
                if str(run["status"]) == "failed":
                    return agent_run_from_row(run)
                row = conn.execute(
                    """UPDATE agent_runs SET status='failed',completed_at=%s,updated_at=%s,terminal_reason_code=%s,terminal_message=%s,claimed_by=NULL,claim_token=NULL,lease_expires_at=NULL WHERE run_id=%s RETURNING *""",
                    (now, now, reason_code, message, run_id),
                ).fetchone()
            return agent_run_from_row(row)
        except (RunNotFound, InvalidRunTransition):
            raise
        except Exception as exc:
            raise StoreError("unable to fail agent run") from exc

    def cancel_run(
        self,
        run_id: str,
        worker_id: str,
        claim_token: str,
        execution_attempt: int,
        reason_code: str,
        now: datetime,
    ) -> AgentRun:
        try:
            with self._pool.connection() as conn:
                row = conn.execute(
                    """UPDATE agent_runs SET status='cancelled',completed_at=%s,updated_at=%s,terminal_reason_code=%s,terminal_message='运行已取消',claimed_by=NULL,claim_token=NULL,lease_expires_at=NULL WHERE run_id=%s AND status='running' AND claimed_by=%s AND claim_token=%s AND execution_attempt=%s RETURNING *""",
                    (
                        now,
                        now,
                        reason_code,
                        run_id,
                        worker_id,
                        claim_token,
                        execution_attempt,
                    ),
                ).fetchone()
                if row is None:
                    row = conn.execute(
                        "SELECT * FROM agent_runs WHERE run_id=%s", (run_id,)
                    ).fetchone()
            if row is None:
                raise RunNotFound
            if str(row["status"]) != "cancelled":
                raise InvalidRunTransition("stale or invalid run claim")
            return agent_run_from_row(row)
        except (RunNotFound, InvalidRunTransition):
            raise
        except Exception as exc:
            raise StoreError("unable to cancel agent run") from exc

    def incompatible_run(
        self,
        run_id: str,
        claim_token: str,
        execution_attempt: int,
        message: str,
        now: datetime,
    ) -> AgentRun:
        try:
            with self._pool.connection() as conn:
                row = conn.execute(
                    """UPDATE agent_runs SET status='incompatible',completed_at=%s,updated_at=%s,terminal_reason_code='runtime_contract_mismatch',terminal_message=%s,claimed_by=NULL,claim_token=NULL,lease_expires_at=NULL WHERE run_id=%s AND status='running' AND claim_token=%s AND execution_attempt=%s RETURNING *""",
                    (now, now, message, run_id, claim_token, execution_attempt),
                ).fetchone()
            if row is None:
                raise InvalidRunTransition("stale or invalid run claim")
            return agent_run_from_row(row)
        except InvalidRunTransition:
            raise
        except Exception as exc:
            raise StoreError("unable to mark incompatible run") from exc

    def _request_replay(
        self,
        conn: Any,
        conversation_id: str,
        client_request_id: str,
        operation: str,
        payload_hash: str,
    ) -> RunCreation | None:
        row = conn.execute(
            """SELECT request.operation,request.payload_hash,run.*,message.*
            FROM run_requests request JOIN agent_runs run USING (run_id)
            JOIN conversation_messages message ON message.message_id=request.input_message_id
            WHERE request.conversation_id=%s AND request.client_request_id=%s""",
            (conversation_id, client_request_id),
        ).fetchone()
        if row is None:
            return None
        expected = "0" * 64 if operation == "retry" else payload_hash
        if str(row["operation"]) != operation or str(row["payload_hash"]) != expected:
            raise IdempotencyConflict
        return RunCreation(agent_run_from_row(row), message_from_row(row))

    @staticmethod
    def _lock_active_conversation(
        conn: Any, owner_id: str, conversation_id: str
    ) -> Any:
        row = conn.execute(
            """SELECT conversation.* FROM conversations conversation
            JOIN owners owner ON owner.owner_id=conversation.owner_id
            WHERE conversation.owner_id=%s AND conversation.conversation_id=%s FOR UPDATE""",
            (owner_id, conversation_id),
        ).fetchone()
        if row is None:
            raise ConversationNotFound
        if str(row["lifecycle_state"]) != "active" or str(
            row["lifecycle_state"]
        ) != str(row.get("lifecycle_state")):
            raise ConversationDeleting
        if str(row["owner_id"]) != owner_id:
            raise ConversationNotFound
        return row

    @staticmethod
    def _require_no_active_run(conn: Any, conversation_id: str) -> None:
        if (
            conn.execute(
                "SELECT 1 FROM agent_runs WHERE conversation_id=%s AND status IN ('queued','running','waiting_approval') LIMIT 1",
                (conversation_id,),
            ).fetchone()
            is not None
        ):
            raise ConversationBusy

    @staticmethod
    def _next_sequence(conn: Any, conversation_id: str) -> int:
        return int(
            conn.execute(
                "SELECT COALESCE(max(sequence),0)+1 AS sequence FROM conversation_messages WHERE conversation_id=%s",
                (conversation_id,),
            ).fetchone()["sequence"]
        )

    @staticmethod
    def _insert_grant(
        conn: Any,
        grant_id: str,
        run_id: str,
        actor: Actor,
        conversation_id: str,
        now: datetime,
    ) -> None:
        conn.execute(
            """INSERT INTO run_grants
            (grant_id,run_id,owner_id,tenant_id,conversation_id,allowed_data_scopes,allowed_action_classes,authorization_epoch,requested_by_session_id,expires_at)
            VALUES (%s,%s,%s,'default',%s,%s::jsonb,%s::jsonb,(SELECT authorization_epoch FROM owners WHERE owner_id=%s),%s,%s)""",
            (
                grant_id,
                run_id,
                actor.owner_id,
                conversation_id,
                json.dumps([f"conversation:{conversation_id}", "owner:memory"]),
                json.dumps(
                    ["model.invoke", "memory.read", "memory.write", "tool.invoke"]
                ),
                actor.owner_id,
                actor.session_id,
                now + timedelta(days=7),
            ),
        )

    @staticmethod
    def _insert_run(
        conn: Any,
        run_id: str,
        conversation_id: str,
        owner_id: str,
        input_message_id: str,
        grant_id: str,
        now: datetime,
        *,
        retry_of_run_id: str | None = None,
    ) -> Any:
        return conn.execute(
            """INSERT INTO agent_runs
            (run_id,conversation_id,owner_id,input_message_id,grant_id,status,runtime_contract_version,retry_of_run_id,created_at,updated_at)
            VALUES (%s,%s,%s,%s,%s,'queued',%s,%s,%s,%s) RETURNING *""",
            (
                run_id,
                conversation_id,
                owner_id,
                input_message_id,
                grant_id,
                RUNTIME_CONTRACT_VERSION,
                retry_of_run_id,
                now,
                now,
            ),
        ).fetchone()

    @staticmethod
    def _lock_claim(
        conn: Any, run_id: str, claim_token: str, execution_attempt: int
    ) -> Any:
        row = conn.execute(
            "SELECT * FROM agent_runs WHERE run_id=%s FOR UPDATE", (run_id,)
        ).fetchone()
        if row is None:
            raise RunNotFound
        if (
            str(row["status"]) != "running"
            or str(row["claim_token"]) != claim_token
            or int(row["execution_attempt"]) != execution_attempt
        ):
            raise InvalidRunTransition("stale or invalid run claim")
        return row
