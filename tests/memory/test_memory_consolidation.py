"""M05 沉淀式写入（consolidation）契约测试（实现交接 §5.1-5.9）。

单点断言都走公开接口；fake extractor 提供确定候选（不调 LLM），
fake clock 控制时间。游标语义与 repo/postgresql/memory 生产 adapter 对齐。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from src.conversation.models import ConversationMessage
from src.memory.long_term.facts import FactCandidate, MergeAction, MergeSuggestion
from src.memory.model_adapters import StructuredMemoryExtractor
from src.memory.ports import MemoryStoreError
from src.memory.service import MemoryService
from src.ownership.models import (
    Actor,
    ExecutionAuthorization,
    OwnerRecord,
    SessionRecord,
)
from src.repo.inmemory import (
    InMemoryOwnershipStore,
    InMemoryPlatformState,
)
from tests.memory._store import InMemoryMemoryStore

NOW = datetime(2026, 8, 5, 8, 0, tzinfo=timezone.utc)
OWNER_ID = "11111111-1111-1111-1111-111111111111"
SESSION_ID = "22222222-2222-2222-2222-222222222222"
CONVERSATION_ID = "cccccccc-cccc-cccc-cccc-cccccccccccc"


class MutableClock:
    def __init__(self, start: datetime = NOW) -> None:
        self.value = start

    def __call__(self) -> datetime:
        return self.value


class FakeConversationStore:
    """只暴露 messages(owner_id, conversation_id) 的最小双。"""

    durable = True

    def __init__(self, messages: tuple[ConversationMessage, ...] = ()) -> None:
        self._messages = messages

    def messages(
        self, owner_id: str, conversation_id: str
    ) -> tuple[ConversationMessage, ...]:
        del owner_id, conversation_id
        return self._messages


class RecordingStore(InMemoryMemoryStore):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.consolidation_enqueues = 0

    def enqueue_job(self, job):
        enqueued = super().enqueue_job(job)
        if enqueued and job.operation == "consolidate":
            self.consolidation_enqueues += 1
        return enqueued


class ReconStore(InMemoryMemoryStore):
    """advance_consolidation_cursor 第一次抛错：模拟写库后、推进前崩溃。"""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.fail_advance = 1

    def advance_consolidation_cursor(
        self, owner_id: str, conversation_id: str, sequence: int, now: datetime
    ) -> bool:
        if self.fail_advance:
            self.fail_advance -= 1
            raise MemoryStoreError("simulated advance failure")
        return super().advance_consolidation_cursor(
            owner_id, conversation_id, sequence, now
        )


class FakeJudge:
    def __init__(self, action: MergeAction = MergeAction.UPDATE) -> None:
        self.action = action
        self.calls: list[tuple[FactCandidate, Any]] = []

    def judge(self, candidate: FactCandidate, previous: Any) -> MergeSuggestion:
        self.calls.append((candidate, previous))
        return MergeSuggestion(self.action, 0.99, previous.memory_id)


class WindowExtractor(StructuredMemoryExtractor):
    """fake：直接返回构造好的候选；记录每次调用与输入。"""

    def __init__(self, reply: Any) -> None:
        super().__init__(lambda _: ())
        self._reply = reply
        self.extract_calls: list[str] = []
        self.window_calls: list[str] = []

    def extract(self, content: str) -> tuple[FactCandidate, ...]:
        self.extract_calls.append(content)
        return self._reply(content)

    def extract_window(self, transcript: str) -> tuple[FactCandidate, ...]:
        self.window_calls.append(transcript)
        return self._reply(transcript)


def _candidate(
    transcript: str,
    *,
    subject: str = "我",
    slot: str,
    value: str,
    fact: str,
    mode: str = "statement",
) -> FactCandidate:
    start = transcript.index(fact)
    return FactCandidate(
        subject=subject,
        slot=slot,
        value=value,
        fact=fact,
        assertion_mode=mode,
        temporal_scope="current",
        confidence=0.99,
        source_span=(start, start + len(fact)),
    )


def _message(sequence: int, role: str, content: str) -> ConversationMessage:
    return ConversationMessage(
        message_id=f"00000000-0000-0000-0001-{sequence:012d}",
        conversation_id=CONVERSATION_ID,
        owner_id=OWNER_ID,
        role=role,  # type: ignore[arg-type]
        content=content,
        sequence=sequence,
        created_at=NOW + timedelta(seconds=sequence),
        client_request_id=(
            f"10000000-0000-0000-0001-{sequence:012d}"
            if role == "user"
            else None
        ),
        source_run_id=(
            f"20000000-0000-0000-0001-{sequence:012d}"
            if role == "assistant"
            else None
        ),
        reply_to_message_id=(
            f"00000000-0000-0000-0001-{sequence - 1:012d}"
            if role == "assistant"
            else None
        ),
    )


def _build(
    *,
    clock: MutableClock | None = None,
    extractor: WindowExtractor | None = None,
    conversation: FakeConversationStore | None = None,
    store: InMemoryMemoryStore | None = None,
    judge: FakeJudge | None = None,
    window_messages: int = 5,
    idle_seconds: int = 600,
    max_input_tokens: int = 4000,
) -> tuple[MemoryService, InMemoryMemoryStore, Actor]:
    state = InMemoryPlatformState(
        owners={OWNER_ID: OwnerRecord(OWNER_ID, "user", "active", 3)},
        sessions={
            SESSION_ID: SessionRecord(
                SESSION_ID, OWNER_ID, "user", "hash", NOW + timedelta(days=1)
            )
        },
    )
    ownership = InMemoryOwnershipStore(state, account_available=True, mode="durable")
    store = store or InMemoryMemoryStore(durable=True)
    service = MemoryService(
        store,
        ownership,
        cursor_secret="x" * 32,
        clock=clock or (lambda: NOW),
        extractor=extractor,
        conflict_judge=judge,
        conversation=conversation,
        window_messages=window_messages,
        idle_seconds=idle_seconds,
        max_input_tokens=max_input_tokens,
    )
    actor = Actor(OWNER_ID, "user", SESSION_ID, "alice", "durable")
    return service, store, actor


def _run_auth(service: MemoryService, actor: Actor) -> ExecutionAuthorization:
    command = service.command_authorization(actor)
    return ExecutionAuthorization(
        run_id="dddddddd-dddd-dddd-dddd-dddddddddddd",
        owner_id=command.owner_id,
        tenant_id=command.tenant_id,
        conversation_id=CONVERSATION_ID,
        allowed_data_scopes=command.allowed_data_scopes,
        allowed_action_classes=command.allowed_action_classes,
        authorization_epoch=command.authorization_epoch,
    )


def _record(service: MemoryService, actor: Actor, sequence: int) -> bool:
    return service.record_user_message_for_consolidation(
        service.command_authorization(actor, action="write"),
        conversation_id=CONVERSATION_ID,
        sequence=sequence,
    )


def _name_candidate(
    transcript: str, fact: str = "我叫林舟", mode: str = "statement"
) -> FactCandidate:
    return _candidate(
        transcript, slot="name", value=fact.removeprefix("我叫"), fact=fact, mode=mode
    )


def _name_reply(transcript: str, *, fact: str = "我叫林舟") -> tuple[FactCandidate, ...]:
    return (_name_candidate(transcript, fact),) if fact in transcript else ()


def _conversation_at(n: int) -> tuple[ConversationMessage, ...]:
    """seq 1..n：用户行与助手行交错（默认窗口语义 = sequence 差）。"""
    return (
        _message(1, "user", "我叫林舟"),
        _message(2, "assistant", "好的。"),
        _message(3, "user", "我住在杭州"),
        _message(4, "assistant", "记住了。"),
        _message(5, "user", "我在上海读过书"),
    )[:n]


def test_window_threshold_enqueues_one_consolidation_job() -> None:
    extractor = WindowExtractor(_name_reply)
    store = RecordingStore(durable=True)
    conversation = FakeConversationStore(_conversation_at(5))
    service, _store, actor = _build(
        extractor=extractor, conversation=conversation, store=store
    )

    for sequence in (1, 2, 3, 4):
        _record(service, actor, sequence)
    # 窗口未满（4 < 5）：不产生任何 consolidate job
    assert service.process_pending_jobs() == 0
    assert store.consolidation_enqueues == 0
    assert extractor.window_calls == []
    assert extractor.extract_calls == []

    assert _record(service, actor, 5)
    assert not _record(service, actor, 5)
    assert store.consolidation_enqueues == 1
    assert service.process_pending_jobs() == 1
    assert len(extractor.window_calls) == 1
    facts = store.active_facts(actor.owner_id, "default")
    assert [(fact.slot, fact.fact) for fact in facts] == [("name", "我叫林舟")]
    cursor = store.get_consolidation_cursor(
        actor.owner_id, "default", CONVERSATION_ID
    )
    assert cursor is not None
    assert cursor.last_consolidated_sequence == 5
    assert cursor.last_message_sequence == 5


def test_insufficient_messages_do_not_enqueue_and_idle_fallback_does() -> None:
    clock = MutableClock()
    extractor = WindowExtractor(_name_reply)
    store = RecordingStore(durable=True)
    conversation = FakeConversationStore(_conversation_at(2))
    service, _store, actor = _build(
        clock=clock,
        extractor=extractor,
        conversation=conversation,
        store=store,
    )

    # 窗口未满（2 < 5）：仅推进游标，不入队
    assert not _record(service, actor, 1)
    assert not _record(service, actor, 2)
    assert service.process_pending_jobs() == 0
    assert store.consolidation_enqueues == 0

    clock.value = NOW + timedelta(seconds=601)
    assert service.process_pending_jobs() == 1
    assert store.consolidation_enqueues == 1
    assert len(extractor.window_calls) == 1
    facts = store.active_facts(actor.owner_id, "default")
    assert [(fact.slot, fact.fact) for fact in facts] == [("name", "我叫林舟")]
    cursor = store.get_consolidation_cursor(
        actor.owner_id, "default", CONVERSATION_ID
    )
    assert cursor is not None and cursor.last_consolidated_sequence == 2


def test_replay_with_advance_failure_converges_via_decide_merge() -> None:
    clock = MutableClock()
    extractor = WindowExtractor(_name_reply)
    conversation = FakeConversationStore(_conversation_at(5))
    service, store, actor = _build(
        clock=clock,
        extractor=extractor,
        conversation=conversation,
        store=ReconStore(durable=True),
    )

    for sequence in (1, 2, 3, 4):
        assert not _record(service, actor, sequence)
    assert _record(service, actor, 5)
    # 第一次 dispatch：写入成功但游标推进失败 → job 被重试
    assert service.process_pending_jobs() == 0
    clock.value = NOW + timedelta(seconds=2)
    # 第二次 dispatch：同窗口重放，decide_merge 收敛，游标推进成功
    # （写入同时入队了 graph projection job，一并完成 → ≥1）
    assert service.process_pending_jobs() >= 1

    assert len(extractor.window_calls) == 2
    facts = store.active_facts(actor.owner_id, "default")
    assert [(fact.slot, fact.fact) for fact in facts] == [("name", "我叫林舟")]
    cursor = store.get_consolidation_cursor(
        actor.owner_id, "default", CONVERSATION_ID
    )
    assert cursor is not None and cursor.last_consolidated_sequence == 5


def test_retraction_within_window_saves_only_latest_value() -> None:
    def reply(transcript: str) -> tuple[FactCandidate, ...]:
        return (
            _name_candidate(transcript, "我叫林舟"),
            _candidate(
                transcript,
                slot="name",
                value="林伟",
                fact="我叫林伟",
                mode="correction",
            ),
        )

    extractor = WindowExtractor(reply)
    conversation = FakeConversationStore(
        _conversation_at(4) + (_message(5, "user", "我叫林伟"),)
    )
    service, store, actor = _build(extractor=extractor, conversation=conversation)

    for sequence in (1, 2, 3, 4):
        assert not _record(service, actor, sequence)
    assert _record(service, actor, 5)
    assert service.process_pending_jobs() == 1
    facts = store.active_facts(actor.owner_id, "default")
    assert [(fact.slot, fact.fact) for fact in facts] == [("name", "我叫林伟")]


def test_secret_message_advances_cursor_but_never_reaches_extractor() -> None:
    extractor = WindowExtractor(_name_reply)
    conversation = FakeConversationStore(
        _conversation_at(2)
        + (_message(3, "user", "我的密钥是 sk-abcdefghijklmn0123456789"),)
        + _conversation_at(5)[3:]
    )
    service, store, actor = _build(extractor=extractor, conversation=conversation)

    for sequence in (1, 2, 3, 4):
        assert not _record(service, actor, sequence)
    assert _record(service, actor, 5)
    assert service.process_pending_jobs() == 1
    assert len(extractor.window_calls) == 1
    assert "sk-" not in extractor.window_calls[0]
    assert "密钥" not in extractor.window_calls[0]
    facts = store.active_facts(actor.owner_id, "default")
    assert [(fact.slot, fact.fact) for fact in facts] == [("name", "我叫林舟")]
    cursor = store.get_consolidation_cursor(
        actor.owner_id, "default", CONVERSATION_ID
    )
    assert cursor is not None and cursor.last_consolidated_sequence == 5


def test_token_budget_splits_early_first_and_advances_to_end() -> None:
    contents = ("我住在杭州", "我住在上海", "我住在北京", "我住在深圳")
    slots = ("city_a", "city_b", "city_c", "city_d")

    def reply(transcript: str) -> tuple[FactCandidate, ...]:
        found: list[FactCandidate] = []
        for content, slot in zip(contents, slots):
            if content in transcript:
                found.append(
                    _candidate(
                        transcript, slot=slot, value=content[3:], fact=content
                    )
                )
        return tuple(found)

    extractor = WindowExtractor(reply)
    conversation = FakeConversationStore(
        tuple(_message(sequence, "user", content) for sequence, content in zip((1, 2, 3, 4), contents))
    )
    service, store, actor = _build(
        extractor=extractor,
        conversation=conversation,
        window_messages=4,
        max_input_tokens=12,  # 每段约 12 tokens，容不下第 2 条消息
    )

    for sequence in (1, 2, 3):
        assert not _record(service, actor, sequence)
    assert _record(service, actor, 4)
    assert service.process_pending_jobs() == 1
    assert len(extractor.window_calls) == 4
    # 早期优先：段序与消息 sequence 一致
    first_seqs = [int(line.split("|")[0][5:]) for line in extractor.window_calls]
    assert first_seqs == sorted(first_seqs)
    facts = store.active_facts(actor.owner_id, "default")
    assert len(facts) == 4
    cursor = store.get_consolidation_cursor(
        actor.owner_id, "default", CONVERSATION_ID
    )
    assert cursor is not None and cursor.last_consolidated_sequence == 4


def test_legacy_extract_job_is_still_dispatched() -> None:
    extractor = WindowExtractor(_name_reply)
    service, store, actor = _build(extractor=extractor)

    auth = service.command_authorization(actor, action="write")
    assert service.enqueue_extraction(
        auth,
        "我叫林舟",
        source_ref="message:legacy",
        source_order=1,
    )
    assert service.process_pending_jobs() == 1
    assert len(extractor.extract_calls) == 1
    facts = store.active_facts(actor.owner_id, "default")
    assert [(fact.slot, fact.fact) for fact in facts] == [("name", "我叫林舟")]


def test_explicit_natural_remember_is_unchanged_and_not_consolidated() -> None:
    extractor = WindowExtractor(_name_reply)
    store = RecordingStore(durable=True)
    service, _store, actor = _build(extractor=extractor, store=store)

    outcome = service.process_natural_intent(
        _run_auth(service, actor),
        "记住，我叫林舟",
        source_ref="message:explicit",
        source_order=1,
    )
    assert outcome is not None and outcome.status == "saved"
    assert len(extractor.extract_calls) == 1
    assert extractor.window_calls == []
    assert store.consolidation_enqueues == 0
    facts = store.active_facts(actor.owner_id, "default")
    assert [(fact.slot, fact.fact) for fact in facts] == [("name", "我叫林舟")]


def test_cross_window_statement_conflict_consults_judge_and_quarantines() -> None:
    judge = FakeJudge(MergeAction.QUARANTINE)

    def reply(transcript: str) -> tuple[FactCandidate, ...]:
        if "我叫林伟" in transcript:
            return (_name_candidate(transcript, "我叫林伟"),)
        return _name_reply(transcript)

    extractor = WindowExtractor(reply)
    conversation = FakeConversationStore(
        _conversation_at(5)
        + (
            _message(6, "user", "我叫林伟"),
            _message(7, "assistant", "好的。"),
            _message(8, "user", "我住在成都"),
            _message(9, "assistant", "记住了。"),
            _message(10, "user", "我在深圳工作"),
        )
    )
    service, store, actor = _build(
        extractor=extractor,
        conversation=conversation,
        judge=judge,
    )

    # 第一窗（seq 1..5）
    for sequence in (1, 2, 3, 4):
        assert not _record(service, actor, sequence)
    assert _record(service, actor, 5)
    assert service.process_pending_jobs() == 1
    facts = store.active_facts(actor.owner_id, "default")
    assert [(fact.slot, fact.fact) for fact in facts] == [("name", "我叫林舟")]

    # 第二窗（seq 6..10）：同槽位改口（statement 模式）→ judge 介入；
    # judge 只有 QUARANTINE 判定生效，冲突走隔离，active 事实不变。
    for sequence in (6, 7, 8, 9):
        assert not _record(service, actor, sequence)
    assert _record(service, actor, 10)
    # 写入同时入队了 graph projection job，一并完成 → ≥1
    assert service.process_pending_jobs() >= 1
    assert len(judge.calls) == 1
    facts = store.active_facts(actor.owner_id, "default")
    assert [(fact.slot, fact.fact) for fact in facts] == [("name", "我叫林舟")]


def test_cross_window_correction_supersedes_existing_fact() -> None:
    """第二窗以 correction 标记改口（不经 judge）→ 既有 supersede（UPDATE）路径。"""
    judge = FakeJudge(MergeAction.UPDATE)

    def reply(transcript: str) -> tuple[FactCandidate, ...]:
        if "我叫林伟" in transcript:
            return (_name_candidate(transcript, "我叫林伟", mode="correction"),)
        return _name_reply(transcript)

    extractor = WindowExtractor(reply)
    conversation = FakeConversationStore(
        _conversation_at(5)
        + (
            _message(6, "user", "我叫林伟"),
            _message(7, "assistant", "好的。"),
            _message(8, "user", "我住在成都"),
            _message(9, "assistant", "记住了。"),
            _message(10, "user", "我在深圳工作"),
        )
    )
    service, store, actor = _build(
        extractor=extractor,
        conversation=conversation,
        judge=judge,
    )
    actor_id = actor.owner_id

    for sequence in (1, 2, 3, 4):
        assert not _record(service, actor, sequence)
    assert _record(service, actor, 5)
    assert service.process_pending_jobs() == 1
    facts = store.active_facts(actor_id, "default")
    assert [(fact.slot, fact.fact) for fact in facts] == [("name", "我叫林舟")]

    for sequence in (6, 7, 8, 9):
        assert not _record(service, actor, sequence)
    assert _record(service, actor, 10)
    # 写入同时入队了 graph projection job，一并完成 → ≥1
    assert service.process_pending_jobs() >= 1
    # correction 短路：judge 不被咨询
    assert len(judge.calls) == 0
    facts = store.active_facts(actor_id, "default")
    assert [(fact.slot, fact.fact) for fact in facts] == [("name", "我叫林伟")]
