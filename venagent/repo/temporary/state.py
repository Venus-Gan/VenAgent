"""temporary 平台 adapter 共享的进程内状态与锁。"""

from __future__ import annotations

# ruff: noqa: F401
from collections import defaultdict, deque
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from threading import RLock
from uuid import uuid4

from ...agent.graph import RUNTIME_CONTRACT_VERSION
from ...agent.runs import (
    ACTIVE_RUN_STATUSES,
    AgentRun,
    InvalidRunTransition,
    RunAuthorizationInvalid,
    RunNotFound,
)
from ...conversation.errors import (
    AnonymousLimitExceeded,
    ConversationBusy,
    ConversationDeleting,
    ConversationNotFound,
    IdempotencyConflict,
    RetryNotAllowed,
)
from ...conversation.models import Conversation, ConversationMessage, RunCreation
from ...ownership.errors import SessionInactive, UsernameTaken
from ...ownership.models import (
    Actor,
    ActorKind,
    ExecutionAuthorization,
    OwnerRecord,
    RefreshLookup,
    RunGrant,
    SessionRecord,
    UserRecord,
)


@dataclass(frozen=True)
class _RequestRecord:
    operation: str
    payload: str
    run_id: str
    input_message_id: str


@dataclass
class TemporaryPlatformState:
    owners: dict[str, OwnerRecord] = field(default_factory=dict)
    users: dict[str, UserRecord] = field(default_factory=dict)
    users_by_name: dict[str, str] = field(default_factory=dict)
    sessions: dict[str, SessionRecord] = field(default_factory=dict)
    conversations: dict[str, Conversation] = field(default_factory=dict)
    messages: dict[str, list[ConversationMessage]] = field(
        default_factory=lambda: defaultdict(list)
    )
    runs: dict[str, AgentRun] = field(default_factory=dict)
    grants: dict[str, RunGrant] = field(default_factory=dict)
    requests: dict[tuple[str, str], _RequestRecord] = field(default_factory=dict)
    guest_creates: dict[str, deque[datetime]] = field(
        default_factory=lambda: defaultdict(deque)
    )
    # ownership 与 conversation/run adapter 共享状态，所有跨表语义必须共用同一把锁。
    lock: RLock = field(default_factory=RLock, repr=False)
