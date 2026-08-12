import { defineStore } from 'pinia'

import { useOwnershipStore } from '../ownership/store'

export type Message = {
  id: string
  role: 'user' | 'assistant'
  text: string
  status: 'sent' | 'thinking' | 'streaming' | 'stopping' | 'failed' | 'cancelled'
  runId?: string
  retryEligible?: boolean
}

export type Run = {
  runId: string
  conversationId: string
  inputMessageId: string
  outputMessageId: string | null
  status: 'queued' | 'running' | 'waiting_approval' | 'succeeded' | 'failed' | 'cancelled' | 'incompatible'
  phase: string | null
  terminalMessage: string | null
  cancelRequested: boolean
  retryEligible: boolean
}

export type Conversation = {
  conversationId: string
  title: string
  titleSource: 'auto' | 'manual'
  messages: Message[]
  runs: Run[]
  updatedAt: number
}

const terminal = new Set(['succeeded', 'failed', 'cancelled', 'incompatible'])

async function readJson(response: Response): Promise<any> {
  const body = await response.text()
  if (!body) return {}
  try {
    return JSON.parse(body)
  } catch {
    return {
      error: {
        message: response.ok ? '服务响应格式无效。' : '服务暂时不可用，请稍后重试。',
      },
    }
  }
}

function mapMessage(item: any): Message {
  return { id: item.message_id, role: item.role, text: item.content, status: 'sent' }
}

function mapRun(item: any): Run {
  return {
    runId: item.run_id,
    conversationId: item.conversation_id,
    inputMessageId: item.input_message_id,
    outputMessageId: item.output_message_id,
    status: item.status,
    phase: item.phase,
    terminalMessage: item.terminal_message,
    cancelRequested: item.cancel_requested_at != null,
    retryEligible: item.retry_eligible === true,
  }
}

export const useChatStore = defineStore('chat', {
  state: () => ({
    activeId: null as string | null,
    conversations: [] as Conversation[],
    currentOwnerId: null as string | null,
    persistenceAvailable: false,
    restartRecoveryAvailable: false,
    historyLoading: false,
    historyOffline: false,
    nextCursor: null as string | null,
    notice: '',
    partialByRun: {} as Record<string, string>,
    observers: new Map<string, AbortController>(),
  }),
  getters: {
    serverConversations(state): Conversation[] {
      return [...state.conversations].sort((a, b) => b.updatedAt - a.updatedAt)
    },
    visibleConversations(): Conversation[] {
      return this.serverConversations
    },
    active(state): Conversation | undefined {
      return state.conversations.find(item => item.conversationId === state.activeId)
    },
    activeRun(): Run | undefined {
      return [...(this.active?.runs || [])].reverse().find(run => !terminal.has(run.status))
    },
    busy(): boolean {
      return !!this.activeRun
    },
    stopping(): boolean {
      return this.activeRun?.cancelRequested === true
    },
    readOnly(): boolean {
      return !this.active || this.historyOffline
    },
    visibleMessages(): Message[] {
      if (!this.active) return []
      const items: Message[] = []
      for (const message of this.active.messages) {
        items.push(message)
        if (message.role !== 'user') continue
        const attempts = this.active.runs.filter(
          run => run.inputMessageId === message.id,
        )
        if (attempts.some(run => !!run.outputMessageId)) continue
        const run = attempts.at(-1)
        if (!run) continue
        if (!terminal.has(run.status)) {
          items.push({
            id: 'partial-' + run.runId,
            role: 'assistant',
            text: this.partialByRun[run.runId] || '',
            status: run.cancelRequested
              ? 'stopping'
              : this.partialByRun[run.runId]
                ? 'streaming'
                : 'thinking',
            runId: run.runId,
          })
        } else if (run.status !== 'succeeded') {
          items.push({
            id: 'attempt-' + run.runId,
            role: 'assistant',
            text: run.terminalMessage || '',
            status: run.status === 'cancelled' ? 'cancelled' : 'failed',
            runId: run.runId,
            retryEligible: run.retryEligible,
          })
        }
      }
      return items
    },
  },
  actions: {
    async initialize() {
      localStorage.removeItem('venagent-conversations-v1')
      localStorage.removeItem('venagent-conversations-v2')
      const ownership = useOwnershipStore()
      await ownership.bootstrap()
      if (!ownership.actor) return
      await this.identityChanged()
      await this.health()
    },
    async health() {
      try {
        const response = await fetch('/health', { cache: 'no-store' })
        const data = await readJson(response)
        this.persistenceAvailable = data.capabilities?.conversation_persistence === 'available'
        this.restartRecoveryAvailable = data.capabilities?.restart_recovery === 'available'
      } catch {
        this.persistenceAvailable = false
        this.restartRecoveryAvailable = false
      }
    },
    async identityChanged() {
      const ownership = useOwnershipStore()
      if (!ownership.actor) return
      this.stopObservers()
      this.currentOwnerId = ownership.actor.owner_id
      this.conversations = []
      this.activeId = null
      this.partialByRun = {}
      await this.loadHistory()
      if (!this.conversations.length && !this.historyOffline) await this.create()
      if (!this.activeId) this.activeId = this.conversations[0]?.conversationId || null
      if (this.activeId) await this.select(this.activeId)
    },
    async loadHistory(cursor?: string) {
      const ownership = useOwnershipStore()
      this.historyLoading = true
      this.notice = ''
      try {
        const query = new URLSearchParams({ limit: '20' })
        if (cursor) query.set('cursor', cursor)
        const response = await ownership.apiFetch('/api/conversations?' + query)
        if (!response.ok) throw new Error()
        const data = await readJson(response)
        const previous = this.conversations
        const incoming: Conversation[] = data.items.map((item: any) => {
          const cached = previous.find(entry => entry.conversationId === item.conversation_id)
          return {
            conversationId: item.conversation_id,
            title: item.title,
            titleSource: item.title_source,
            messages: cached?.messages || [],
            runs: cached?.runs || [],
            updatedAt: Date.parse(item.updated_at),
          }
        })
        if (!cursor) this.conversations = []
        for (const item of incoming) this.upsert(item)
        this.nextCursor = data.next_cursor
        this.historyOffline = false
      } catch {
        this.historyOffline = true
        this.notice = '对话列表暂时无法读取，请稍后重试。'
      } finally {
        this.historyLoading = false
      }
    },
    async loadMore() {
      if (this.nextCursor) await this.loadHistory(this.nextCursor)
    },
    async create() {
      const ownership = useOwnershipStore()
      if (!ownership.actor || this.historyOffline) return
      try {
        const response = await ownership.apiFetch('/api/conversations', { method: 'POST' })
        const data = await readJson(response)
        if (!response.ok) throw new Error(data.error?.message)
        const conversation: Conversation = {
          conversationId: data.conversation_id,
          title: data.title,
          titleSource: data.title_source,
          messages: [],
          runs: [],
          updatedAt: Date.parse(data.updated_at),
        }
        this.upsert(conversation)
        this.activeId = conversation.conversationId
      } catch (error: any) {
        this.notice = error?.message || '无法创建对话。'
      }
    },
    async select(conversationId: string) {
      this.activeId = conversationId
      const conversation = this.conversations.find(item => item.conversationId === conversationId)
      if (!conversation) return
      const ownership = useOwnershipStore()
      try {
        const response = await ownership.apiFetch('/api/conversations/' + encodeURIComponent(conversationId))
        if (response.status === 404) {
          this.conversations = this.conversations.filter(item => item !== conversation)
          this.activeId = this.conversations[0]?.conversationId || null
          return
        }
        const data = await readJson(response)
        if (!response.ok) throw new Error(data.error?.message)
        conversation.title = data.title
        conversation.titleSource = data.title_source
        conversation.updatedAt = Date.parse(data.updated_at)
        conversation.messages = data.messages.map(mapMessage)
        conversation.runs = data.runs.map(mapRun)
        for (const run of conversation.runs) {
          if (!terminal.has(run.status)) void this.observe(run.runId)
        }
        this.historyOffline = false
      } catch (error: any) {
        this.notice = error?.message || '对话详情暂时无法读取。'
      }
    },
    async rename(conversation: Conversation, title: string) {
      const previous = conversation.title
      conversation.title = title.trim()
      const ownership = useOwnershipStore()
      try {
        const response = await ownership.apiFetch(
          '/api/conversations/' + encodeURIComponent(conversation.conversationId),
          { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title }) },
        )
        const data = await readJson(response)
        if (!response.ok) throw new Error(data.error?.message)
        conversation.title = data.title
        conversation.titleSource = data.title_source
      } catch (error: any) {
        conversation.title = previous
        this.notice = error?.message || '标题修改失败。'
      }
    },
    async remove(conversation: Conversation) {
      if (!confirm('删除“' + conversation.title + '”？此操作无法撤销。')) return
      const ownership = useOwnershipStore()
      try {
        const response = await ownership.apiFetch(
          '/api/conversations/' + encodeURIComponent(conversation.conversationId),
          { method: 'DELETE' },
        )
        if (!response.ok && response.status !== 404) throw new Error()
        this.conversations = this.conversations.filter(item => item !== conversation)
        if (this.activeId === conversation.conversationId) {
          this.activeId = this.conversations[0]?.conversationId || null
        }
        if (!this.conversations.length) await this.create()
      } catch {
        this.notice = '删除失败，对话仍保留。'
      }
    },
    async send(text: string) {
      const conversation = this.active
      if (!conversation || this.readOnly || this.busy || !text.trim()) return
      const ownership = useOwnershipStore()
      try {
        const response = await ownership.apiFetch(
          '/api/conversations/' + encodeURIComponent(conversation.conversationId) + '/runs',
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: text, client_request_id: crypto.randomUUID() }),
          },
        )
        const data = await readJson(response)
        if (!response.ok) throw new Error(data.error?.message)
        if (data.kind === 'memory_command') {
          this.notice = data.message
          return
        }
        const message = mapMessage(data.input_message)
        if (!conversation.messages.some(item => item.id === message.id)) conversation.messages.push(message)
        const run = mapRun(data.run)
        this.upsertRun(conversation, run)
        void this.observe(run.runId)
      } catch (error: any) {
        this.notice = error?.message || '发送失败，请稍后重试。'
      }
    },
    async retry(runId: string) {
      const ownership = useOwnershipStore()
      const response = await ownership.apiFetch('/api/runs/' + encodeURIComponent(runId) + '/retry', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ client_request_id: crypto.randomUUID() }),
      })
      const data = await readJson(response)
      if (!response.ok) {
        this.notice = data.error?.message || '当前任务无法重试。'
        return
      }
      const conversation = this.conversations.find(item => item.conversationId === data.run.conversation_id)
      if (!conversation) return
      const run = mapRun(data.run)
      this.upsertRun(conversation, run)
      void this.observe(run.runId)
    },
    async cancel() {
      const run = this.activeRun
      if (!run || run.cancelRequested) return
      const ownership = useOwnershipStore()
      try {
        const response = await ownership.apiFetch('/api/runs/' + encodeURIComponent(run.runId) + '/cancel', { method: 'POST' })
        if (!response.ok) {
          this.notice = '取消请求未能提交，请稍后重试。'
          return
        }
        const data = await readJson(response)
        if (data.status !== 'cancel_requested') {
          await this.pollRun(run.runId)
          return
        }
        // 202 只确认请求已持久接受；终态仍等待服务端 snapshot。
        run.cancelRequested = true
      } catch {
        this.notice = '取消请求未能提交，请稍后重试。'
      }
    },
    async observe(runId: string) {
      if (this.observers.has(runId)) return
      const ownership = useOwnershipStore()
      const controller = new AbortController()
      this.observers.set(runId, controller)
      try {
        const response = await ownership.apiFetch('/api/runs/' + encodeURIComponent(runId) + '/events', { signal: controller.signal })
        if (!response.ok || !response.body) throw new Error()
        const reader = response.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''
        for (;;) {
          const chunk = await reader.read()
          buffer += decoder.decode(chunk.value || new Uint8Array(), { stream: !chunk.done }).replace(/\r\n/g, '\n')
          const blocks = buffer.split('\n\n')
          buffer = blocks.pop() || ''
          for (const block of blocks) this.consumeEvent(runId, block)
          if (chunk.done) break
        }
      } catch {
        if (!controller.signal.aborted) await this.pollRun(runId)
      } finally {
        if (this.observers.get(runId) === controller) this.observers.delete(runId)
      }
    },
    consumeEvent(runId: string, block: string) {
      const event = block.match(/^event:\s*(.*)$/m)?.[1]
      const raw = block.match(/^data:\s*(.*)$/m)?.[1]
      if (!event || !raw) return
      const data = JSON.parse(raw)
      if (data.run_id !== runId) return
      if (event === 'token') {
        const run = this.conversations
          .flatMap(conversation => conversation.runs)
          .find(item => item.runId === runId)
        if (run?.cancelRequested) return
        this.partialByRun[runId] = (this.partialByRun[runId] || '') + (data.content || '')
      } else if (event === 'snapshot') {
        this.applyRun(mapRun(data.run))
      }
    },
    async pollRun(runId: string) {
      const ownership = useOwnershipStore()
      for (;;) {
        const response = await ownership.apiFetch('/api/runs/' + encodeURIComponent(runId))
        if (!response.ok) return
        const run = mapRun(await readJson(response))
        this.applyRun(run)
        if (terminal.has(run.status)) return
        await new Promise(resolve => window.setTimeout(resolve, 1000))
      }
    },
    applyRun(run: Run) {
      const conversation = this.conversations.find(item => item.conversationId === run.conversationId)
      if (!conversation) return
      this.upsertRun(conversation, run)
      if (terminal.has(run.status)) {
        delete this.partialByRun[run.runId]
        void this.select(run.conversationId)
      }
    },
    upsertRun(conversation: Conversation, run: Run) {
      const index = conversation.runs.findIndex(item => item.runId === run.runId)
      if (index >= 0) conversation.runs[index] = run
      else conversation.runs.push(run)
    },
    upsert(conversation: Conversation) {
      const index = this.conversations.findIndex(item => item.conversationId === conversation.conversationId)
      if (index >= 0) this.conversations[index] = conversation
      else this.conversations.push(conversation)
    },
    stopObservers() {
      for (const controller of this.observers.values()) controller.abort()
      this.observers.clear()
    },
    invalidateIdentity() {
      this.stopObservers()
      this.currentOwnerId = null
      this.activeId = null
      this.conversations = []
      this.partialByRun = {}
    },
  },
})
