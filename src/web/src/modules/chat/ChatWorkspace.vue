<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import OwnershipDialog from '../ownership/OwnershipDialog.vue'
import OwnershipPanel from '../ownership/OwnershipPanel.vue'
import { useOwnershipStore } from '../ownership/store'
import DshIcon from './DshIcon.vue'
import PlanWindow from './PlanWindow.vue'
import TrajectoryPanel from './TrajectoryPanel.vue'
import { operationFailureLabel, useChatStore, type CommandOption, type Conversation, type Message } from './store'

const chat = useChatStore()
const ownership = useOwnershipStore()
const text = ref('')
const sidebarOpen = ref(false)
const isNarrow = ref(false)
const editingId = ref<string | null>(null)
const editingTitle = ref('')
const menuButton = ref<HTMLButtonElement | null>(null)
const composerInput = ref<HTMLTextAreaElement | null>(null)
const messagesContainer = ref<HTMLElement | null>(null)
const followLatest = ref(true)
const viewMode = ref<'chat' | 'trajectory'>('chat')
const processingOpenByRun = ref<Record<string, boolean>>({})
const toolCallExpandedById = ref<Record<string, boolean>>({})
const thinkExpandedById = ref<Record<string, boolean>>({})
const slashOpen = ref(false)
const slashIndex = ref(0)
// M07 澄清卡片：每张卡片的本地选择态（单选存一项，多选存数组，custom 为"其他"输入）。
const clarifySelectedByCard = ref<Record<string, string[]>>({})
const clarifyCustomByCard = ref<Record<string, string>>({})
const clarifySubmittingByCard = ref<Record<string, boolean>>({})
const busy = computed(() => chat.busy)
const stopping = computed(() => chat.stopping)
const bottomThresholdPx = 64
const filteredOptions = computed(() => {
  if (!slashOpen.value) return []
  const value = text.value.trimStart()
  if (!value.startsWith('/')) return []
  const tokens = value.split(/\s+/).filter(Boolean)
  const hasParent = tokens.length > 1 || /\s$/.test(value)
  const parent = hasParent ? `/${tokens[0].replace(/^\//, '')}` : null
  const query = parent ? value.toLowerCase() : value.slice(1).toLowerCase()
  return chat.slashOptions.filter(option => {
    if (parent && option.parent !== parent) return false
    if (!parent && option.parent) return false
    const label = option.label.toLowerCase()
    return label.includes(query) || option.detail.toLowerCase().includes(query)
  })
})
const selectedSkillLabel = computed(() => {
  const option = chat.slashOptions.find(item => item.skillId === chat.selectedSkillId)
  return option?.label || chat.selectedSkillId || ''
})
const activeRenderSignature = computed(() => {
  const conversation = chat.active
  if (!conversation) return ''
  const messages = chat.visibleMessages
  const last = messages.at(-1)
  let lastAssistant: Message | undefined
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    if (messages[index].role === 'assistant') {
      lastAssistant = messages[index]
      break
    }
  }
  return [
    conversation.conversationId,
    messages.length,
    last?.id || '',
    lastAssistant?.id || '',
    lastAssistant?.text.length || 0,
    lastAssistant?.status || '',
  ].join('|')
})

let viewportQuery: MediaQueryList | undefined
let pendingScrollFrame: number | null = null

function bottomDistance(element: HTMLElement) {
  return Math.max(0, element.scrollHeight - element.scrollTop - element.clientHeight)
}

function cancelPendingScroll() {
  if (pendingScrollFrame !== null && pendingScrollFrame >= 0) cancelAnimationFrame(pendingScrollFrame)
  pendingScrollFrame = null
}

async function scheduleScrollToLatest(force = false) {
  if (force) followLatest.value = true
  if (viewMode.value !== 'chat') return
  if (!followLatest.value || pendingScrollFrame !== null) return
  const targetThreadId = chat.activeId
  pendingScrollFrame = -1
  await nextTick()
  if (pendingScrollFrame !== -1) return
  pendingScrollFrame = requestAnimationFrame(() => {
    pendingScrollFrame = null
    const element = messagesContainer.value
    if (!element || chat.activeId !== targetThreadId || !followLatest.value) return
    element.scrollTop = element.scrollHeight
  })
}

function handleMessagesScroll() {
  const element = messagesContainer.value
  if (element) followLatest.value = bottomDistance(element) <= bottomThresholdPx
}

function syncViewport() {
  isNarrow.value = viewportQuery?.matches ?? false
  if (!isNarrow.value) sidebarOpen.value = false
}

function closeSidebar(restoreFocus = true) {
  sidebarOpen.value = false
  if (restoreFocus && isNarrow.value) nextTick(() => menuButton.value?.focus())
}

function handleKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape' && sidebarOpen.value) closeSidebar()
}

function handleComposerKeydown(event: KeyboardEvent) {
  const options = filteredOptions.value
  const exactTopLevelCommand = chat.slashOptions.some(
    option => !option.parent && option.label === text.value.trim(),
  )
  if (event.key === 'Enter' && !event.shiftKey && exactTopLevelCommand) {
    event.preventDefault()
    slashOpen.value = false
    submitOrCancel()
    return
  }
  if (options.length) {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      slashIndex.value = (slashIndex.value + 1) % options.length
      return
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault()
      slashIndex.value = (slashIndex.value - 1 + options.length) % options.length
      return
    }
    if (event.key === 'Enter' || event.key === 'Tab') {
      event.preventDefault()
      chooseSlashOption(options[slashIndex.value] || options[0])
      return
    }
    if (event.key === 'Escape') {
      slashOpen.value = false
      return
    }
  }
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    submitOrCancel()
  }
}

function chooseSlashOption(option: CommandOption) {
  if (option.kind === 'skill' && option.skillId) {
    chat.selectSkill(option.skillId)
    text.value = ''
    slashOpen.value = false
    void nextTick(resizeComposer)
    return
  }
  text.value = option.label + ' '
  slashOpen.value = true
  void nextTick(resizeComposer)
}

function handleIdentityFallback() {
  void identityChanged()
}

async function handleIdentityInvalidated() {
  chat.invalidateIdentity()
  try {
    await ownership.revalidateIdentity()
    await identityChanged()
  } catch {
    ownership.error = '身份重新确认失败，旧账号内容已隐藏。'
  }
}

function handlePageHide() {
  chat.stopObservers()
}

async function createConversation() {
  await chat.create()
  closeSidebar(false)
  await scheduleScrollToLatest(true)
}

async function selectConversation(conversationId: string) {
  cancelPendingScroll()
  await chat.select(conversationId)
  closeSidebar(false)
  await scheduleScrollToLatest(true)
}

async function identityChanged() {
  cancelPendingScroll()
  await chat.identityChanged()
  closeSidebar(false)
  await scheduleScrollToLatest(true)
}

async function refreshHistory() {
  await chat.loadHistory()
  await scheduleScrollToLatest(true)
}

async function beginRename(conversation: Conversation) {
  editingId.value = conversation.conversationId
  editingTitle.value = conversation.title
  await nextTick()
  document.querySelector<HTMLInputElement>(`[data-title-id="${conversation.conversationId}"]`)?.select()
}

async function finishRename(conversation: Conversation) {
  if (editingId.value !== conversation.conversationId) return
  const value = editingTitle.value.trim()
  editingId.value = null
  if (value && value !== conversation.title) await chat.rename(conversation, value)
}

function resizeComposer() {
  const input = composerInput.value
  if (!input) return
  input.style.height = '0px'
  input.style.height = `${Math.min(input.scrollHeight, 140)}px`
  input.style.overflowY = input.scrollHeight > 140 ? 'auto' : 'hidden'
}

async function submit() {
  const value = text.value.trim()
  if (!value) return
  viewMode.value = 'chat'
  followLatest.value = true
  text.value = ''
  await nextTick()
  resizeComposer()
  await chat.send(value, chat.selectedSkillId)
}

function submitOrCancel() {
  if (busy.value) {
    if (!stopping.value) void chat.cancel()
    return
  }
  void submit()
}

function messageStateLabel(message: Message) {
  if (message.status === 'streaming') return '生成中'
  if (message.status === 'thinking') return '思考中'
  if (message.status === 'stopping') return '正在停止'
  if (message.status === 'cancelled') return '已取消'
  return '运行失败'
}

async function decideApproval(runId: string, event: any, approved: boolean) {
  if (!event.approvalId) return
  try {
    await chat.decideApproval(runId, event.approvalId, approved)
  } catch (error: any) {
    chat.notice = error?.message || '审批操作失败'
  }
}

// M07 澄清卡片交互：单选/多选/其他自填/忽略。
function toggleClarifyOption(cardId: string, option: string, multiSelect: boolean) {
  const current = clarifySelectedByCard.value[cardId] || []
  if (!multiSelect) {
    clarifySelectedByCard.value[cardId] = current.includes(option) && current.length === 1 ? [] : [option]
    return
  }
  clarifySelectedByCard.value[cardId] = current.includes(option)
    ? current.filter(item => item !== option)
    : [...current, option]
}

function clarifySelection(cardId: string): string[] {
  return clarifySelectedByCard.value[cardId] || []
}

function clarifyHasAnswer(cardId: string): boolean {
  return clarifySelection(cardId).length > 0 || !!clarifyCustomByCard.value[cardId]?.trim()
}

async function submitClarification(message: Message, skipped: boolean) {
  const runId = message.runId
  if (!runId || clarifySubmittingByCard.value[message.id]) return
  clarifySubmittingByCard.value[message.id] = true
  try {
    await chat.submitClarification(runId, {
      selected: clarifySelection(message.id),
      custom: skipped ? null : (clarifyCustomByCard.value[message.id]?.trim() || null),
      skipped,
    })
  } catch (error: any) {
    chat.notice = error?.message || '澄清答复提交失败'
  } finally {
    clarifySubmittingByCard.value[message.id] = false
  }
}

function processingEventsForRun(runId: string) {
  return chat.processingByRun[runId] || []
}

function trajectoryEventsForRun(runId: string) {
  return chat.trajectoryByRun[runId] || []
}

// M07 任务视窗：最近一个带 Plan 的 run 的轨迹事件（组件内派生节点状态）。
const planWindowEvents = computed(() => {
  const runId = chat.planWindowRunId
  return runId ? (chat.trajectoryByRun[runId] || []) : []
})

function visibleTrajectoryEventsForRun(runId: string) {
  return trajectoryEventsForRun(runId).filter(
    event => event.type !== 'run.started' && event.type !== 'run.completed',
  )
}

function reasoningSummary(text: string, streaming = false) {
  const lines = text.split(/\r?\n/).map(item => item.trim()).filter(Boolean)
  if (!lines.length) return '正在思考'
  return streaming ? lines[lines.length - 1] : lines[0]
}

function hasReasoningBlock(message: Message) {
  return !!message.blocks?.some(block => block.type === 'reasoning')
}

function toolIconName(event: any): 'bash' | 'code' | 'search' | 'edit' | 'sparkle' | 'skill' {
  const toolId = String(event?.toolId || '')
  if (toolId === 'exec_command' || toolId === 'bash' || toolId === 'terminal') return 'bash'
  if (toolId.includes('skill')) return 'skill'
  if (toolId.includes('search') || toolId.includes('fetch') || toolId.includes('web')) return 'search'
  if (toolId.includes('write') || toolId.includes('edit') || toolId.includes('patch') || toolId.includes('str_replace')) return 'edit'
  if (toolId.includes('code') || toolId.includes('python') || toolId.includes('node')) return 'code'
  return 'sparkle'
}

function toolCallFailureLabel(message: Message) {
  return message.processingEvent
    ? operationFailureLabel(message.processingEvent)
    : (message.failureLabel || '执行失败')
}

function toolCallExpanded(message: Message) {
  const explicit = toolCallExpandedById.value[message.id]
  if (explicit !== undefined) return explicit
  // 待审批的操作默认展开详情，保证审批按钮立即可见可点。
  return message.toolStatus === 'awaiting_approval'
}

// 运行中折叠态展示最新一行思考内容；展开显示全部。
function liveReasoning(runId?: string) {
  if (!runId) return ''
  const partial = (chat.partialBlocksByRun[runId] || []).filter(b => b.type === 'reasoning')
  const text = partial.at(-1)?.text || chat.reasoningByRun[runId] || ''
  const lines = text.split(/\r?\n/).map(item => item.trim()).filter(Boolean)
  return lines.at(-1) || ''
}

// 完成态折叠行：有思考内容显示首行，没有则占位提示。
function reasoningSummaryInline(runId?: string) {
  const text = fullReasoning(runId)
  if (!text) return '本次运行没有返回思考内容'
  const lines = text.split(/\r?\n/).map(item => item.trim()).filter(Boolean)
  return lines[0] || ''
}

function fullReasoning(runId?: string) {
  if (!runId) return ''
  const partial = (chat.partialBlocksByRun[runId] || []).filter(b => b.type === 'reasoning')
  const joined = partial.map(b => b.text).join('\n\n')
  return joined || chat.reasoningByRun[runId] || ''
}

function retry(message: Message) {
  if (message.runId && message.retryEligible) {
    followLatest.value = true
    void chat.retry(message.runId)
  }
}

watch(
  () => `${chat.currentOwnerId || ''}:${chat.activeId || ''}`,
  () => {
    cancelPendingScroll()
    void scheduleScrollToLatest(true)
  },
  { flush: 'post' },
)

watch(activeRenderSignature, () => {
  if (followLatest.value) void scheduleScrollToLatest()
}, { flush: 'post' })

watch(text, (value) => {
  if (value.trim()) chat.commandNotice = ''
  slashOpen.value = value.trimStart().startsWith('/')
  slashIndex.value = 0
  if (slashOpen.value) void chat.loadControl()
})

watch(viewMode, (value) => {
  if (value === 'trajectory') {
    void nextTick(() => {
      if (messagesContainer.value) messagesContainer.value.scrollTop = 0
    })
  } else if (value === 'chat') {
    void scheduleScrollToLatest(true)
  }
})

onMounted(async () => {
  viewportQuery = window.matchMedia('(max-width: 720px)')
  syncViewport()
  viewportQuery.addEventListener('change', syncViewport)
  window.addEventListener('keydown', handleKeydown)
  window.addEventListener('venagent:identity-fallback', handleIdentityFallback)
  window.addEventListener('venagent:identity-invalidated', handleIdentityInvalidated)
  window.addEventListener('pagehide', handlePageHide)
  await chat.initialize()
  await nextTick()
  resizeComposer()
  await scheduleScrollToLatest(true)
})

onBeforeUnmount(() => {
  cancelPendingScroll()
  viewportQuery?.removeEventListener('change', syncViewport)
  window.removeEventListener('keydown', handleKeydown)
  window.removeEventListener('venagent:identity-fallback', handleIdentityFallback)
  window.removeEventListener('venagent:identity-invalidated', handleIdentityInvalidated)
  window.removeEventListener('pagehide', handlePageHide)
})
</script>

<template>
  <main v-if="!ownership.bootstrapped" class="bootstrap-screen" aria-live="polite">
    <div class="bootstrap-card">
      <strong>VenAgent</strong>
      <span>正在确认当前身份与对话模式…</span>
    </div>
  </main>

  <main v-else class="shell">
    <button v-if="isNarrow && sidebarOpen" class="sidebar-scrim" type="button" aria-label="关闭会话列表" @click="closeSidebar()" />

    <aside id="conversation-sidebar" class="sidebar" :class="{ 'is-open': sidebarOpen }" :aria-hidden="isNarrow && !sidebarOpen ? 'true' : 'false'" :inert="isNarrow && !sidebarOpen" @keydown.esc="closeSidebar()">
      <div class="sidebar-heading">
        <div>
          <div class="brand">VenAgent</div>
          <span class="mode-badge" :class="ownership.mode">{{ ownership.modeLabel }}</span>
        </div>
        <button class="sidebar-close" type="button" aria-label="关闭会话列表" @click="closeSidebar()">&times;</button>
      </div>

      <button class="new" type="button" :disabled="chat.historyOffline" @click="createConversation">＋ 新对话</button>

      <section class="history-section" aria-labelledby="server-history-label">
        <div class="section-heading">
          <span id="server-history-label">{{ ownership.isUser ? '账号历史' : '匿名对话' }}</span>
          <button type="button" aria-label="刷新历史" @click="refreshHistory">刷新</button>
        </div>
        <div v-if="chat.historyLoading" class="section-empty">正在加载…</div>
        <div v-else-if="!chat.serverConversations.length" class="section-empty">暂无服务端对话</div>
        <nav class="sessions" aria-label="服务端对话列表">
          <div v-for="conversation in chat.serverConversations" :key="conversation.conversationId" class="session" :class="{ active: conversation.conversationId === chat.activeId }">
            <button class="session-main" type="button" @click="selectConversation(conversation.conversationId)">
              <input v-if="editingId === conversation.conversationId" :data-title-id="conversation.conversationId" v-model="editingTitle" maxlength="100" aria-label="对话标题" @click.stop @blur="finishRename(conversation)" @keydown.enter.prevent="finishRename(conversation)" @keydown.esc.prevent="editingId = null" />
              <span v-else class="session-title">{{ conversation.title }}</span>
              <span class="session-meta">{{ conversation.messages.length }} 条本机可见消息</span>
            </button>
            <button class="rename" type="button" :aria-label="`重命名 ${conversation.title}`" @click="beginRename(conversation)">✎</button>
            <button class="remove" type="button" :aria-label="`删除 ${conversation.title}`" @click="chat.remove(conversation)">&times;</button>
          </div>
        </nav>
        <button v-if="chat.nextCursor" class="load-more" type="button" @click="chat.loadMore()">加载更多</button>
      </section>

      <OwnershipPanel @identity-changed="identityChanged" />
    </aside>

    <section class="workspace">
      <header class="topbar">
        <button ref="menuButton" class="sidebar-toggle" type="button" aria-label="打开会话列表" aria-controls="conversation-sidebar" :aria-expanded="sidebarOpen" @click="sidebarOpen = true">&#9776;</button>
        <div>
          <div class="title">{{ chat.active?.title || '新对话' }}</div>
          <div class="meta">
            {{ chat.historyOffline ? '历史同步失败，当前缓存只读' : chat.persistenceAvailable ? '服务端历史已启用' : '临时匿名模式；服务重启后内容可能丢失' }}
          </div>
        </div>
        <div class="topbar-links">
          <RouterLink class="control-link" to="/documents">文档库</RouterLink>
          <RouterLink class="control-link" to="/settings">设置</RouterLink>
          <RouterLink class="control-link" to="/control">控制面</RouterLink>
        </div>
      </header>

      <div class="status-stack">
        <div v-if="chat.historyOffline" class="offline-banner" role="status">账号身份有效，但历史服务暂时不可用；当前缓存只读。</div>
        <div v-if="chat.notice || ownership.error" class="notice" role="status">{{ chat.notice || ownership.error }}</div>
      </div>

      <nav class="view-tabs" role="tablist" aria-label="对话视图">
        <button type="button" role="tab" :aria-selected="viewMode === 'chat'" :class="{ active: viewMode === 'chat' }" @click="viewMode = 'chat'">对话</button>
        <button type="button" role="tab" :aria-selected="viewMode === 'trajectory'" :class="{ active: viewMode === 'trajectory' }" @click="viewMode = 'trajectory'">轨迹</button>
      </nav>

      <section ref="messagesContainer" class="messages" :class="{ 'trajectory-mode': viewMode === 'trajectory' }" aria-live="polite" @scroll="handleMessagesScroll">
        <TrajectoryPanel v-if="viewMode === 'trajectory'" />
        <template v-else>
          <div v-if="!chat.visibleMessages.length" class="empty">
            <h1>开始一段新对话</h1>
            <p>{{ ownership.isUser ? '成功完成的轮次会同步到账号历史。' : '无需登录即可使用；登录不会迁移匿名历史。' }}</p>
          </div>
          <article v-for="message in chat.visibleMessages" :key="message.id" class="row" :class="message.role">            <div>
              <div v-if="message.role === 'skill'" class="skill-call">
                <DshIcon name="skill" :size="14" class="skill-call-icon" />
                <span class="skill-call-label">Skill</span>
                <span class="skill-call-name">{{ message.skillLabel || message.text }}</span>
              </div>
              <div
                v-else-if="message.role === 'thinking'"
                class="think-block"
                :class="{ 'is-failed': message.status === 'failed', 'is-cancelled': message.status === 'cancelled' }"
                :role="message.status === 'failed' ? 'alert' : undefined"
              >
                <template v-if="message.status === 'failed' || message.status === 'cancelled'">
                  <button
                    type="button"
                    class="think-head"
                    :aria-expanded="thinkExpandedById[message.id] === true"
                    :aria-controls="`think-details-${message.id}`"
                    @click="thinkExpandedById[message.id] = !thinkExpandedById[message.id]"
                  >
                    <span class="think-dot" aria-hidden="true"></span>
                    <span class="think-title">{{ message.status === 'cancelled' ? '已取消' : '运行失败' }}</span>
                    <span class="think-summary-inline">{{ message.terminalMessage || message.text }}</span>
                    <span class="think-toggle" :class="{ 'is-open': thinkExpandedById[message.id] === true }" aria-hidden="true">›</span>
                  </button>
                  <div v-if="thinkExpandedById[message.id]" :id="`think-details-${message.id}`" class="think-details think-error">
                    {{ message.terminalMessage || message.text }}
                  </div>
                </template>
                <template v-else-if="message.status === 'succeeded'">
                  <button
                    type="button"
                    class="think-head"
                    :aria-expanded="thinkExpandedById[message.id] === true"
                    :aria-controls="`think-details-${message.id}`"
                    @click="thinkExpandedById[message.id] = !thinkExpandedById[message.id]"
                  >
                    <span class="think-dot is-done" aria-hidden="true"></span>
                    <span class="think-title">思考完成</span>
                    <span class="think-summary-inline">{{ reasoningSummaryInline(message.runId) }}</span>
                    <span class="think-toggle" :class="{ 'is-open': thinkExpandedById[message.id] === true }" aria-hidden="true">›</span>
                  </button>
                  <div v-if="thinkExpandedById[message.id]" :id="`think-details-${message.id}`" class="think-details">{{ fullReasoning(message.runId) || '本次运行没有返回思考内容。' }}</div>
                </template>
                <template v-else>
                  <button
                    type="button"
                    class="think-head"
                    :aria-expanded="thinkExpandedById[message.id] === true"
                    :aria-controls="`think-details-${message.id}`"
                    @click="thinkExpandedById[message.id] = !thinkExpandedById[message.id]"
                  >
                    <span class="think-dot is-pulse" aria-hidden="true"></span>
                    <span class="think-title">思考中</span>
                    <span class="think-summary-inline">{{ liveReasoning(message.runId) || '正在思考...' }}</span>
                    <span class="think-toggle" :class="{ 'is-open': thinkExpandedById[message.id] === true }" aria-hidden="true">›</span>
                  </button>
                  <div v-if="thinkExpandedById[message.id]" :id="`think-details-${message.id}`" class="think-details">{{ fullReasoning(message.runId) || '正在思考...' }}</div>
                </template>
              </div>
              <div v-else-if="message.role === 'clarification' && message.clarification" class="clarify-card" role="group" :aria-label="`澄清：${message.clarification.question}`">
                <div class="clarify-head">
                  <span class="clarify-badge">需要确认</span>
                  <span class="clarify-question">{{ message.clarification.question }}</span>
                </div>
                <div v-if="message.clarification.options.length" class="clarify-options">
                  <button
                    v-for="option in message.clarification.options"
                    :key="option"
                    type="button"
                    class="clarify-option"
                    :class="{ active: clarifySelection(message.id).includes(option) }"
                    :aria-pressed="clarifySelection(message.id).includes(option)"
                    @click="toggleClarifyOption(message.id, option, message.clarification!.multiSelect)"
                  >
                    <span class="clarify-option-mark" aria-hidden="true">{{ message.clarification.multiSelect ? (clarifySelection(message.id).includes(option) ? '☑' : '☐') : (clarifySelection(message.id).includes(option) ? '◉' : '○') }}</span>
                    <span>{{ option }}</span>
                  </button>
                </div>
                <label class="clarify-custom">
                  <span>其他</span>
                  <input v-model="clarifyCustomByCard[message.id]" type="text" maxlength="2000" placeholder="自行填写…" :disabled="clarifySubmittingByCard[message.id] === true" />
                </label>
                <div class="clarify-actions">
                  <button type="button" class="clarify-skip" :disabled="clarifySubmittingByCard[message.id] === true" @click="submitClarification(message, true)">忽略，按你的判断继续</button>
                  <button type="button" class="clarify-confirm" :disabled="!clarifyHasAnswer(message.id) || clarifySubmittingByCard[message.id] === true" @click="submitClarification(message, false)">
                    {{ clarifySubmittingByCard[message.id] ? '提交中…' : '确认' }}
                  </button>
                </div>
              </div>
              <div v-else-if="message.role === 'tool_call'" class="tool-call">
                <button
                  type="button"
                  class="tool-call-head"
                  @click="toolCallExpandedById[message.id] = !toolCallExpanded(message)"
                  :aria-expanded="toolCallExpanded(message)"
                >
                  <DshIcon :name="toolIconName(message.processingEvent)" :size="14" class="tool-call-icon" />
                  <span class="tool-call-name">{{ message.processingEvent?.source === 'mcp' ? `MCP/${message.processingEvent?.serverId || 'server'}` : 'Native' }} · {{ message.toolId || message.text }}</span>
                  <span class="tool-call-status" :class="message.status">{{ message.toolStatus }}</span>
                  <span v-if="message.status === 'failed'" class="tool-call-failure-label">{{ toolCallFailureLabel(message) }}</span>
                  <span v-if="message.errorCode" class="error-code-badge">{{ message.errorCode }}</span>
                  <span v-if="message.elapsedMs !== undefined && message.elapsedMs !== null" class="tool-call-time">{{ message.elapsedMs }} ms</span>
                  <span class="tool-call-toggle" :class="{ 'is-open': toolCallExpandedById[message.id] === true }" aria-hidden="true">›</span>
                </button>
                <div v-if="toolCallExpanded(message)" class="tool-call-details">
                  <div v-if="message.errorCode" class="tool-call-detail">
                    <strong>错误码：</strong>{{ message.errorCode }}
                  </div>
                  <div v-if="message.argumentsSummary" class="tool-call-detail">
                    <strong>参数：</strong>{{ message.argumentsSummary }}
                  </div>
                  <div v-if="message.processingEvent?.riskReason" class="tool-call-detail">
                    <strong>风险：</strong>{{ message.processingEvent.riskReason }}
                  </div>
                  <div v-if="message.resultSummary" class="tool-call-detail">
                    <strong>结果：</strong>{{ message.resultSummary }}
                  </div>
                  <div v-if="message.processingEvent?.artifacts.length" class="tool-call-detail">
                    <strong>Artifact：</strong>{{ message.processingEvent.artifacts.length }}
                  </div>
                  <div v-if="message.processingEvent?.approvalId && message.processingEvent?.status === 'awaiting_approval'" class="tool-call-approval">
                    待审批
                    <button type="button" @click="decideApproval(message.runId || '', message.processingEvent, true)">批准</button>
                    <button type="button" @click="decideApproval(message.runId || '', message.processingEvent, false)">拒绝</button>
                  </div>
                </div>
              </div>
              <div v-else class="bubble" :class="{ 'error-bubble': message.status === 'failed' }" :role="message.status === 'failed' ? 'alert' : undefined">
                <details v-if="message.role === 'assistant' && message.status === 'thinking' && !hasReasoningBlock(message)" class="reasoning-row">
                  <summary>
                    <DshIcon name="think" :size="14" class="reasoning-icon" />
                    <span class="reasoning-title">Think</span>
                    <span class="reasoning-summary">正在思考</span>
                  </summary>
                </details>
                <template v-if="message.role === 'assistant' && message.blocks?.length">
                  <template v-for="(block, index) in message.blocks" :key="`reasoning-${message.id}-${index}`">
                    <details v-if="block.type === 'reasoning'" class="reasoning-row">
                      <summary>
                        <DshIcon name="think" :size="14" class="reasoning-icon" />
                        <span class="reasoning-title">Think</span>
                        <span class="reasoning-summary">{{ reasoningSummary(block.text, message.status === 'streaming') }}</span>
                      </summary>
                      <div class="reasoning-content">{{ block.text }}</div>
                    </details>
                  </template>
                </template>
                <div
                  v-if="message.role === 'assistant' && message.runId && (visibleTrajectoryEventsForRun(message.runId).length || processingEventsForRun(message.runId).length)"
                  class="processing-panel reply-processing"
                >
                  <button class="processing-toggle" type="button" :aria-expanded="processingOpenByRun[message.runId] === true" @click="processingOpenByRun[message.runId] = !processingOpenByRun[message.runId]">
                    <span>执行轨迹</span>
                    <span>{{ processingOpenByRun[message.runId] ? '−' : '+' }}</span>
                  </button>
                  <div v-if="processingOpenByRun[message.runId]" class="processing-list">
                    <div v-for="event in visibleTrajectoryEventsForRun(message.runId)" :key="`trajectory-${event.sequence}`" class="processing-item trajectory-item">
                      <span class="processing-tool">{{ event.label }}</span>
                      <span class="processing-status">{{ event.status }}</span>
                    </div>
                    <div v-for="event in processingEventsForRun(message.runId)" :key="event.operationId" class="processing-item">
                      <DshIcon :name="toolIconName(event)" :size="12" class="processing-tool-icon" />
                      <span class="processing-tool">{{ event.source === 'mcp' ? `MCP/${event.serverId || 'server'}` : 'Native' }} · {{ event.toolId }}</span>
                      <span class="processing-operation">Operation {{ event.operationId.slice(0, 8) }}</span>
                      <span class="processing-status">{{ event.status }}</span>
                      <span v-if="event.timingMs !== null" class="processing-time">{{ event.timingMs }} ms</span>
                      <span v-if="event.argumentsSummary" class="processing-arguments">参数：{{ event.argumentsSummary }}</span>
                      <span v-if="event.riskReason" class="processing-reason">{{ event.riskReason }}</span>
                      <span v-if="event.resultSummary" class="processing-summary">{{ event.resultSummary }}</span>
                      <span v-if="event.artifacts.length" class="processing-artifacts">Artifact {{ event.artifacts.length }}</span>
                      <span v-if="event.approvalId && event.status === 'awaiting_approval'" class="processing-approval">
                        待审批
                        <button type="button" @click="decideApproval(message.runId, event, true)">批准</button>
                        <button type="button" @click="decideApproval(message.runId, event, false)">拒绝</button>
                      </span>
                    </div>
                  </div>
                </div>
                <template v-if="message.role === 'assistant' && message.blocks?.length">
                  <template v-for="(block, index) in message.blocks" :key="`text-${message.id}-${index}`">
                    <div v-if="block.type === 'text'" class="assistant-text">{{ block.text }}</div>
                  </template>
                </template>
                <template v-else>{{ message.text }}</template>
              </div>
              <div
                v-if="message.status !== 'sent' && message.role !== 'tool_call' && !(message.role === 'thinking' && message.status !== 'failed' && message.status !== 'cancelled')"
                class="state"
              >
                {{ messageStateLabel(message) }}
                <button v-if="(message.role === 'assistant' || message.role === 'thinking') && message.retryEligible && !chat.readOnly" class="retry" type="button" @click="retry(message)">重试</button>
              </div>
            </div>
          </article>
        </template>
      </section>

      <form class="composer" @submit.prevent="submitOrCancel">
        <PlanWindow
          v-if="viewMode === 'chat' && planWindowEvents.length"
          class="plan-window-float"
          :events="planWindowEvents"
        />
        <div v-if="chat.selectedSkillId" class="skill-tag">
          <span>{{ selectedSkillLabel }}</span>
          <button type="button" aria-label="移除已选 Skill" @click="chat.clearSkill()">×</button>
        </div>
        <div v-if="chat.commandNotice" class="command-popover" role="status" aria-live="polite">
          <span data-testid="command-options">可用命令</span>
          <pre data-testid="command-result">{{ chat.commandNotice }}</pre>
        </div>
        <div v-if="slashOpen && filteredOptions.length" class="slash-menu" role="listbox" aria-label="命令与 Skill">
          <button v-for="(option, index) in filteredOptions" :key="option.id" type="button" role="option" :aria-selected="index === slashIndex" :class="{ active: index === slashIndex }" @mousedown.prevent="chooseSlashOption(option)" @mouseenter="slashIndex = index">
            <strong>{{ option.label }}</strong>
            <span>{{ option.detail }}</span>
          </button>
        </div>
        <textarea ref="composerInput" v-model="text" rows="1" :disabled="chat.readOnly || stopping" aria-label="输入消息" :placeholder="chat.readOnly ? '当前对话为只读' : stopping ? '正在停止当前运行' : '输入消息，Enter 发送，Shift+Enter 换行'" @input="resizeComposer" @keydown="handleComposerKeydown" />
        <button class="send" type="submit" :disabled="chat.readOnly || stopping" :aria-label="stopping ? '正在停止' : busy ? '停止生成' : '发送'">{{ busy ? '■' : '↑' }}</button>
      </form>
    </section>
  </main>

  <OwnershipDialog @identity-changed="identityChanged" />
</template>
