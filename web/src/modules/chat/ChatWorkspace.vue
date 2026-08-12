<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import OwnershipDialog from '../ownership/OwnershipDialog.vue'
import OwnershipPanel from '../ownership/OwnershipPanel.vue'
import { useOwnershipStore } from '../ownership/store'
import { useChatStore, type Conversation, type Message } from './store'

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
const busy = computed(() => chat.busy)
const stopping = computed(() => chat.stopping)
const bottomThresholdPx = 64
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
  followLatest.value = true
  text.value = ''
  await nextTick()
  resizeComposer()
  await chat.send(value)
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
      </header>

      <div class="status-stack">
        <div v-if="chat.historyOffline" class="offline-banner" role="status">账号身份有效，但历史服务暂时不可用；当前缓存只读。</div>
        <div v-if="chat.notice || ownership.error" class="notice" role="status">{{ chat.notice || ownership.error }}</div>
      </div>

      <section ref="messagesContainer" class="messages" aria-live="polite" @scroll="handleMessagesScroll">
        <div v-if="!chat.visibleMessages.length" class="empty">
          <h1>开始一段新对话</h1>
          <p>{{ ownership.isUser ? '成功完成的轮次会同步到账号历史。' : '无需登录即可使用；登录不会迁移匿名历史。' }}</p>
        </div>
        <article v-for="message in chat.visibleMessages" :key="message.id" class="row" :class="message.role">
          <div class="avatar">{{ message.role === 'user' ? '你' : 'AI' }}</div>
          <div>
            <div class="bubble">{{ message.text }}</div>
            <div v-if="message.status !== 'sent'" class="state">
              {{ messageStateLabel(message) }}
              <button v-if="message.role === 'assistant' && message.retryEligible && !chat.readOnly" class="retry" type="button" @click="retry(message)">重试</button>
            </div>
          </div>
        </article>
      </section>

      <form class="composer" @submit.prevent="submitOrCancel">
        <textarea ref="composerInput" v-model="text" rows="1" :disabled="chat.readOnly || stopping" aria-label="输入消息" :placeholder="chat.readOnly ? '当前对话为只读' : stopping ? '正在停止当前运行' : '输入消息，Enter 发送，Shift+Enter 换行'" @input="resizeComposer" @keydown.enter.exact.prevent="submitOrCancel" />
        <button class="send" type="submit" :disabled="chat.readOnly || stopping" :aria-label="stopping ? '正在停止' : busy ? '停止生成' : '发送'">{{ busy ? '■' : '↑' }}</button>
      </form>
    </section>
  </main>

  <OwnershipDialog @identity-changed="identityChanged" />
</template>
