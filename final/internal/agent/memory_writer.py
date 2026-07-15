# memory_writer — 异步记忆写入与回复中事实抽取
#
#   - extract_memory_from_reply：从 assistant 回复抽取 k-v 事实，分类后通过
#     LongTerm.store_classified 入库（含 embed + PG 写 + 图 add_to_graph 一站式），
#     再调 sync_last_item_pg_id 把 PG 真实主键回写到内存与图。
#   - classify_memory_content：4 条规则 (identity/preference/tool_failure/policy)。
#   - llm_classify_memory：7 类 6 槽 LLM 兜底。
#   - sync_consolidation_to_db：把 ConsolidationResult 落到 PG（批删 + 逐条 update）。
#
# 额外提供 AsyncMemoryWriter：后台线程 + queue.Queue 串行化所有记忆写入，
# 避免 PG/Milvus 并发竞争。
import json
import logging
import queue
import re
import threading
from typing import Any, Dict, List, Optional, Tuple

from internal.llm.llm import Message

logger = logging.getLogger(__name__)


def _publish_event(agent, event_type: str, payload: Dict[str, Any]) -> None:
    try:
        repo = getattr(getattr(agent, "inf", None), "repo", None) or getattr(agent, "repo", None)
        events = getattr(repo, "events", None) if repo is not None else None
        if events is not None and hasattr(events, "publish"):
            events.publish(event_type, json.dumps(payload, ensure_ascii=False))
    except Exception as e:
        logger.warning("⚠️  publish_event(%s) 失败: %s", event_type, e)


# ── 异步记忆写入器 ──────────────────────────────────────────────────────────

class AsyncMemoryWriter:
    """后台线程串行化记忆写入。

    使用 queue.Queue 排队写任务，单 worker 线程消费，避免 ltm/preference 同时
    被多线程改写。stop() 触发优雅退出。
    """

    def __init__(self):
        self._queue: queue.Queue = queue.Queue()
        self._stopped = threading.Event()
        self._worker = threading.Thread(target=self._run, name="memory-writer", daemon=True)
        self._worker.start()

    def submit(self, fn):
        """提交一个无参可调用，最终在 worker 线程执行。"""
        if self._stopped.is_set():
            return
        try:
            self._queue.put_nowait(fn)
        except Exception as e:
            logger.warning("⚠️  memory-writer 提交失败: %s", e)

    def stop(self):
        self._stopped.set()
        try:
            self._queue.put_nowait(None)  # 唤醒 worker
        except Exception:
            pass

    def _run(self):
        while not self._stopped.is_set():
            try:
                fn = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if fn is None:
                break
            try:
                fn()
            except Exception as e:
                logger.warning("⚠️  memory-writer 任务异常: %s", e)


# ── 公共工具 ───────────────────────────────────────────────────────────────


def _strip_code_fence(raw: str) -> str:
    raw = (raw or "").strip()
    raw = re.sub(r"^```json", "", raw)
    raw = re.sub(r"^```", "", raw)
    raw = re.sub(r"```$", "", raw)
    return raw.strip()


def _embed(agent, content: str) -> Optional[List[float]]:
    """优先复用 LongTerm._embed_fn（避免重复构造 embedder）。"""
    fn = getattr(getattr(agent, "ltm", None), "_embed_fn", None)
    if fn is None:
        fn = getattr(agent, "_embed_fn", None)
    if fn is None:
        return None
    try:
        return fn(content)
    except Exception as e:
        logger.warning("⚠️  embed 失败: %s", e)
        return None


# ── 回复 → 记忆抽取 ────────────────────────────────────────────────────────

def extract_memory_from_reply(agent, answer: str):
    """从 assistant 回复中提取值得记忆的 k-v 事实并存入长期记忆。

      1) LLM 抽 k-v；
      2) 写偏好仓 (agent.preference.set)；
      3) classify_memory_content → 失败 fallback llm_classify_memory；
      4) embed → graph_mem.store_classified（含图 + 内存 + PG 一站式）；
         若无 graph_mem，回退 ltm.store_classified；
      5) 调 sync_last_item_pg_id 用 PG 主键校正内存与图节点 ID。
    """
    if not answer or not agent.cfg.is_real_llm():
        return

    prompt = (
        "从下面这段AI回复中，提取值得长期记住的客观事实或用户偏好信息。\n"
        "只提取明确的、非临时性的信息，忽略对话上下文和临时细节。\n"
        "输出 JSON 对象（key为中文名称，value为具体值），如果没有值得记忆的信息则输出 {}。\n"
        "只输出 JSON，不要有其他内容。\n\n"
        f"回复：{answer}"
    )
    try:
        raw = agent.llm.chat([Message(role="user", content=prompt)], system_prompt="")
    except Exception as e:
        logger.warning("⚠️  记忆抽取 LLM 调用失败: %s", e)
        return

    raw = _strip_code_fence(raw)
    try:
        kvs = json.loads(raw)
    except Exception:
        return
    if not isinstance(kvs, dict) or not kvs:
        return

    for k, v in kvs.items():
        if not k or v in (None, ""):
            continue
        try:
            agent.preference.set(str(k), str(v))
        except Exception:
            pass

        content = f"用户{k}: {v}"
        category, tags, slot_hint = classify_memory_content(str(k), str(v))
        if not category:
            category, tags, slot_hint = llm_classify_memory(agent, content)

        emb = _embed(agent, content)
        importance = 0.7

        try:
            inserted = _store_classified_with_graph(
                agent, content, importance, emb, category, tags, slot_hint
            )
        except Exception as e:
            logger.warning("⚠️  长期记忆写入失败: %s", e)
            inserted = False

        logger.info(
            "🧠 从回复中提取记忆：%s = %s（类别=%s，新增=%s）",
            k, v, category, inserted,
        )


def _store_classified_with_graph(
    agent,
    content: str,
    importance: float,
    emb: Optional[List[float]],
    category: str,
    tags: List[str],
    slot_hint: str,
) -> bool:
    """统一走 LongTerm.store_classified 路径；命中 dedup 时返回 False。

    LongTerm.store_classified 内部已串起 [内存写 → PG save (RETURNING id) →
    graph_mem.add_to_graph] 三件事，store_classified 命中 dedup 时返回 False。
    新增成功后调 graph_mem.sync_last_item_pg_id（如挂载）让图侧 prev_id 与
    PG 主键保持一致。
    """
    ltm = agent.ltm
    inserted = ltm.store_classified(
        content,
        importance,
        emb,
        category or "general",
        list(tags or []),
        slot_hint or "",
    )
    if inserted:
        gm = getattr(agent, "graph_memory", None) or getattr(ltm, "graph_memory", None)
        last_id = ltm.last_id() if hasattr(ltm, "last_id") else -1
        if gm is not None and last_id > 0 and hasattr(gm, "sync_last_item_pg_id"):
            try:
                gm.sync_last_item_pg_id(last_id)
            except Exception as e:
                logger.warning("⚠️  graph_mem.sync_last_item_pg_id 失败: %s", e)
    return inserted


def classify_memory_content(key: str, value: str) -> Tuple[str, List[str], str]:
    """用规则快速分类；返回空字符串表示规则未命中，由 LLM 兜底。"""
    combined = f"{key}{value}"
    if _contains_any(combined, "叫", "名字", "姓名", "是我", "我是"):
        return "identity", ["name"], "profile"
    if _contains_any(combined, "喜欢", "偏好", "习惯", "爱好", "讨厌", "不喜欢"):
        return "preference", ["preference"], "profile"
    if _contains_any(combined, "工具", "失败", "错误", "报错", "异常"):
        return "tool_failure", ["tool", "error"], "tool_state"
    if _contains_any(combined, "禁止", "不要", "不能", "必须", "强制"):
        return "policy", ["constraint"], "constraints"
    return "", [], ""


def _contains_any(s: str, *subs: str) -> bool:
    return any(sub in s for sub in subs)


def llm_classify_memory(agent, content: str) -> Tuple[str, List[str], str]:
    """LLM 兜底分类（7 类 6 槽）；失败时回退到 'general'。"""
    if not agent.cfg.is_real_llm():
        return "general", [], ""

    prompt = (
        "请对以下记忆内容进行分类，只输出 JSON，格式如下：\n"
        '{"category":"identity|preference|fact|episodic|tool_failure|policy|general",'
        '"tags":["tag1"],"slot_hint":"profile|planner|task_memory|tool_state|constraints|recall_memory"}\n'
        f"\n记忆内容：{content}"
    )
    try:
        raw = agent.llm.chat([Message(role="user", content=prompt)], system_prompt="")
    except Exception:
        return "general", [], ""
    raw = _strip_code_fence(raw)
    try:
        result = json.loads(raw)
    except Exception:
        return "general", [], ""
    if not isinstance(result, dict):
        return "general", [], ""
    cat = result.get("category") or "general"
    return cat, list(result.get("tags") or []), result.get("slot_hint") or ""


# ── consolidate 后落库 ─────────────────────────────────────────────────────


def sync_consolidation_to_db(agent, result) -> None:
    """把 ConsolidationResult 同步到 PG。

    流程：
      1) 批量删除 result.delete_from_db；
      2) 逐条 update result.update_in_db（每条 marshal embedding 后调 repo.ltm.update）。

    错误粗粒度：单步失败仅打 warning，不中断后续步骤、不回滚。
    """
    if result is None:
        return
    repo = getattr(getattr(agent, "inf", None), "repo", None) or getattr(agent, "repo", None)
    ltm_repo = getattr(repo, "ltm", None) if repo is not None else None
    if ltm_repo is None:
        return

    delete_ids = list(getattr(result, "delete_from_db", []) or [])
    if delete_ids:
        try:
            ltm_repo.delete(delete_ids)
            _publish_event(agent, "memory.consolidate.delete", {"ids": delete_ids, "count": len(delete_ids)})
            logger.info("🧹 记忆合并：删除 %d 条 (ids=%s)", len(delete_ids), delete_ids)
        except Exception as e:
            logger.warning("⚠️  sync_consolidation_to_db delete 失败: %s", e)

    for item in getattr(result, "update_in_db", []) or []:
        item_id = getattr(item, "id", None)
        if item_id is None or item_id <= 0:
            continue
        try:
            emb_json = json.dumps(item.embedding) if item.embedding else "null"
            ltm_repo.update(int(item_id), item.content, float(item.importance), emb_json)
            _publish_event(agent, "memory.consolidate.update", {
                "id": int(item_id),
                "importance": float(item.importance),
                "content": item.content,
            })
            logger.info("🔗 记忆合并：更新 id=%d", int(item_id))
        except Exception as e:
            logger.warning("⚠️  sync_consolidation_to_db update id=%s 失败: %s", item_id, e)


# ── ReAct 模式下的同步 + 异步偏好提取（保留原 agent.py 的实现）──────────────

def async_update_memory(agent, user_input: str, resp: Any) -> None:
    """ReAct 入口前的偏好抽取：

      1) 同步：用规则提取，立即填到 resp.extracted_info（用户即时反馈）
      2) 异步：丢到 memory writer 线程做 LLM 提取 + 长期记忆写入
    """
    try:
        from internal.llm.llm import _extract_rule_based
    except Exception:
        _extract_rule_based = None  # type: ignore

    # 1) 同步规则提取
    if _extract_rule_based is not None:
        try:
            quick = _extract_rule_based(user_input) or {}
        except Exception:
            quick = {}
        if quick:
            try:
                agent.preference.save_batch(quick)
            except Exception:
                pass
            if hasattr(resp, "extracted_info"):
                resp.extracted_info = "已记住：" + ", ".join(f"{k}={v}" for k, v in quick.items())

    # 2) 异步 LLM 提取 + LTM 写入
    def _bg():
        try:
            extracted = agent.llm.extract_preferences(user_input) if hasattr(agent.llm, "extract_preferences") else {}
            if extracted:
                agent.preference.save_batch(extracted)
            agent.ltm.add(user_input)
        except Exception as e:
            logger.warning("异步更新记忆失败: %s", e)

    writer = getattr(agent, "memory_writer", None)
    if writer is not None:
        writer.submit(_bg)
    else:
        threading.Thread(target=_bg, name="memory-fallback", daemon=True).start()


def maybe_consolidate_memory(agent):
    """达到触发阈值时合并/去重/衰减/淘汰长期记忆，并把结果同步到 PG。

    有 graph_memory 时走 ``graph_aware_consolidate``（保护高中心度节点 + 同步删 Neo4j），
    否则走纯内存 ``ltm.consolidate``。
    """
    try:
        if not agent.ltm.need_consolidation():
            return
        gm = getattr(agent, "graph_memory", None)
        if gm is not None and hasattr(gm, "graph_aware_consolidate"):
            result = gm.graph_aware_consolidate()
        else:
            result = agent.ltm.consolidate()
    except Exception as e:
        logger.warning("记忆合并失败: %s", e)
        return
    try:
        sync_consolidation_to_db(agent, result)
    except Exception as e:
        logger.warning("记忆合并落库失败: %s", e)
