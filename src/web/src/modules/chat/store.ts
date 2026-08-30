import { defineStore } from 'pinia'

import { useOwnershipStore } from '../ownership/store'

export type Message = {
  id: string
  role: 'user' | 'assistant' | 'tool' | 'skill' | 'thinking' | 'tool_call' | 'clarification'
  text: string
  status: 'sent' | 'thinking' | 'streaming' | 'stopping' | 'failed' | 'cancelled' | 'succeeded' | 'running' | 'pending'
  runId?: string
  retryEligible?: boolean
  blocks?: AssistantBlock[]
  processingEvent?: ProcessingEvent
  skillLabel?: string
  // tool_call 专用字段
  operationId?: string
  toolId?: string
  argumentsSummary?: string
  resultSummary?: string
  elapsedMs?: number
  toolStatus?: string
  errorCode?: string | null
  failureLabel?: string
  riskReason?: string | null
  // run 失败/取消活动块专用字段（think 块承载）
  terminalMessage?: string | null
  runFailed?: boolean
  // clarification 专用字段（M07 澄清 HITL）
  clarification?: ClarificationRequest
}

export type ClarificationRequest = {
  question: string
  options: string[]
  multiSelect: boolean
}

export type AssistantBlock = {
  type: 'text' | 'reasoning'
  text: string
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
  selectedSkillId?: string | null
  selectedSkillName?: string | null
}

export type Conversation = {
  conversationId: string
  title: string
  titleSource: 'auto' | 'manual'
  messages: Message[]
  runs: Run[]
  updatedAt: number
}

export type CommandOption = {
  id: string
  label: string
  detail: string
  kind: 'command' | 'skill'
  skillId?: string
  parent?: string | null
}

export type ProcessingEvent = {
  operationId: string
  toolId: string
  toolCallId: string
  status: string
  risk: string
  errorCode: string | null
  approvalId: string | null
  resultSummary: string | null
  source: string
  serverId: string | null
  argumentsSummary: string | null
  riskReason: string | null
  timingMs: number | null
  artifacts: string[]
}

export type TrajectoryEvent = {
  sequence: number
  type: string
  label: string
  status: string
  kind?: string
  toolId?: string
  toolCallId?: string
  operationId?: string
  summary?: string | null
  errorCode?: string | null
  timingMs?: number | null
  artifacts?: string[]
  source?: string
  serverId?: string | null
  argumentsSummary?: string | null
  riskReason?: string | null
  // M07 计划视窗：计划/节点事件透传字段
  branch?: string
  revision?: number
  nodeId?: string
  nodes?: PlanWindowNode[]
  appended?: PlanWindowNode[]
  winner?: string
  group?: string
  trigger?: string
  action?: string
  detail?: string
}

export type PlanWindowNode = {
  id: string
  goal: string
  tool: string | null
  agent: string | null
  dependsOn: string[]
  raceGroup: string | null
}

export type PlanWindowNodeStatus = 'pending' | 'running' | 'succeeded' | 'failed' | 'skipped' | 'cancelled'

export type PlanWindow = {
  revision: number
  nodes: Array<PlanWindowNode & { status: PlanWindowNodeStatus; summary: string | null; errorCode: string | null }>
  counts: { running: number; pending: number; done: number; failed: number }
  replansUsed: number | null
  gaveUp: boolean
}

const terminal = new Set(['succeeded', 'failed', 'cancelled', 'incompatible'])
const terminalOperationStatuses = new Set(['succeeded', 'failed', 'cancelled', 'rejected', 'error', 'incompatible'])
const failedOperationStatuses = new Set(['failed', 'rejected', 'error', 'incompatible'])

export function isTerminalOperation(status: string): boolean {
  return terminalOperationStatuses.has(status)
}

export function isFailedOperation(status: string): boolean {
  return failedOperationStatuses.has(status)
}

export function operationFailureLabel(event: Pick<ProcessingEvent, 'status' | 'errorCode'>): string {
  if (event.status === 'cancelled') return '已取消'
  if (event.status === 'rejected' || event.errorCode === 'approval_rejected') return '审批被拒'
  // 网关超时码为 tool_timeout；sandbox 内命令超时为 command_timeout，两者同义。
  if (event.errorCode === 'command_timeout' || event.errorCode === 'tool_timeout') return '命令超时'
  if (event.errorCode?.startsWith('sandbox_')) return '沙箱错误'
  return '执行失败'
}

function trajectoryLabel(type: string): string {
  const labels: Record<string, string> = {
    'run.started': '开始处理',
    'run.completed': '处理完成',
    'run.failed': '处理失败',
    'run.cancelled': '已取消',
    'run.cancel_requested': '收到停止请求',
    'run.incompatible': '运行版本不兼容',
    'run.waiting_clarification': '等待澄清答复',
    'tool.event': '工具调用',
    'approval.event': '审批状态',
    'route.selected': '意图路由',
    'plan.planning_started': '开始规划',
    'plan.created': '计划生成',
    'plan.degraded': '计划降级（走基线执行）',
    'plan.nodes_dropped': '计划节点清洗',
    'plan.layer_started': '执行层开始',
    'plan.replan_decision': '重规划决策',
    'plan.revised': '计划修订',
    'plan.replan_exhausted': '重规划额度用尽',
    'plan.replan_rolled_back': '修订回滚',
    'node.started': '节点开始',
    'node.completed': '节点完成',
    'node.failed': '节点失败',
    'race.won': '竞速胜出',
    'clarification.requested': '发起澄清',
    'rag.retrieved': '知识库检索',
  }
  return labels[type] || type
}

function trajectoryStatus(type: string): string {
  if (type === 'run.completed') return 'completed'
  if (type === 'run.failed' || type === 'run.cancelled' || type === 'run.incompatible') return 'failed'
  return 'running'
}

function mapRunEvent(item: { sequence: number; type: string; payload: any }): TrajectoryEvent {
  const payload = item.payload || {}
  const toolStatus = payload.kind === 'completed'
    ? 'completed'
    : payload.kind === 'failed' || payload.kind === 'cancelled'
      ? 'failed'
      : payload.kind === 'awaiting_approval'
        ? 'awaiting_approval'
        : 'running'
  return {
    sequence: item.sequence,
    type: item.type,
    label: trajectoryLabel(item.type),
    status: item.type === 'tool.event'
      ? payload.status || toolStatus
      : payload.status || trajectoryStatus(item.type),
    kind: item.type === 'tool.event' ? payload.kind : undefined,
    toolId: payload.tool_id,
    toolCallId: payload.tool_call_id,
    operationId: payload.operation_id,
    summary: payload.summary ?? null,
    errorCode: payload.error_code ?? null,
    timingMs: payload.timing_ms ?? null,
    artifacts: payload.artifacts || [],
    source: payload.source,
    serverId: payload.server_id ?? null,
    argumentsSummary: payload.arguments ?? null,
    riskReason: payload.risk_reason ?? null,
    branch: payload.branch,
    revision: payload.revision,
    nodeId: payload.node_id,
    nodes: mapPlanNodes(payload.nodes),
    appended: mapPlanNodes(payload.appended_nodes),
    winner: payload.winner,
    group: payload.group,
    trigger: payload.trigger,
    action: payload.action,
    detail: payload.detail,
  }
}

function mapPlanNodes(raw: any): PlanWindowNode[] | undefined {
  if (!Array.isArray(raw)) return undefined
  return raw
    .filter((item: any) => item && typeof item === 'object')
    .map((item: any) => ({
      id: String(item.id ?? ''),
      goal: String(item.goal ?? ''),
      tool: item.tool != null ? String(item.tool) : null,
      agent: item.agent != null ? String(item.agent) : null,
      dependsOn: Array.isArray(item.depends_on) ? item.depends_on.map(String) : [],
      raceGroup: item.race_group != null ? String(item.race_group) : null,
    }))
}

/**
 * M07 任务视窗派生（对齐 DSH planSummary 语义）：从轨迹事件重建计划与逐节点状态。
 * SSE/event-log 是唯一事实源，本函数是纯派生，不持有第二状态。
 */
export function derivePlanWindow(events: TrajectoryEvent[]): PlanWindow | null {
  let revision = 0
  let replansUsed: number | null = null
  let gaveUp = false
  const nodes = new Map<string, PlanWindowNode & { status: PlanWindowNodeStatus; summary: string | null; errorCode: string | null }>()
  let seenPlan = false
  for (const event of events) {
    if (event.type === 'plan.created' && event.nodes?.length) {
      seenPlan = true
      revision = event.revision ?? 1
      nodes.clear()
      for (const node of event.nodes) {
        nodes.set(node.id, { ...node, status: 'pending', summary: null, errorCode: null })
      }
      continue
    }
    if (event.type === 'plan.degraded') {
      // 计划降级走基线执行：无清单可显示。
      return null
    }
    if (!seenPlan) continue
    if (event.type === 'plan.revised') {
      if (event.revision) revision = event.revision
      for (const node of event.appended || []) {
        if (!nodes.has(node.id)) nodes.set(node.id, { ...node, status: 'pending', summary: null, errorCode: null })
      }
      continue
    }
    if (event.type === 'plan.replan_decision') {
      replansUsed = (replansUsed ?? 0) + 1
      continue
    }
    if (event.type === 'plan.replan_exhausted') {
      gaveUp = true
      continue
    }
    if (event.type === 'node.started') {
      const node = nodes.get(event.nodeId ?? '')
      if (node) node.status = 'running'
      continue
    }
    if (event.type === 'node.completed') {
      const node = nodes.get(event.nodeId ?? '')
      if (node) {
        node.status = 'succeeded'
        node.summary = event.summary ?? null
      }
      continue
    }
    if (event.type === 'node.failed') {
      const node = nodes.get(event.nodeId ?? '')
      if (node) {
        node.status = 'failed'
        node.summary = event.summary ?? null
        node.errorCode = event.errorCode ?? null
      }
      continue
    }
    if (event.type === 'node.skipped') {
      const node = nodes.get(event.nodeId ?? '')
      if (node) {
        node.status = 'skipped'
        node.summary = '竞速落败，结果弃用。'
      }
      continue
    }
  }
  if (!seenPlan || nodes.size === 0) return null
  const list = [...nodes.values()]
  return {
    revision,
    nodes: list,
    counts: {
      running: list.filter(item => item.status === 'running').length,
      pending: list.filter(item => item.status === 'pending').length,
      done: list.filter(item => item.status === 'succeeded' || item.status === 'skipped').length,
      failed: list.filter(item => item.status === 'failed').length,
    },
    replansUsed,
    gaveUp,
  }
}

// tool.event 的 kind → operation 状态（对齐 OperationRecord 状态机；
// 轨迹展示状态由 mapRunEvent 承载，两者终态词汇不同）。
function operationStatusFromKind(kind: string | undefined, resultStatus: string | undefined): string {
  if (kind === 'completed') return resultStatus === 'success' ? 'succeeded' : 'failed'
  if (kind === 'failed') return 'failed'
  if (kind === 'cancelled') return 'cancelled'
  if (kind === 'awaiting_approval') return 'awaiting_approval'
  return 'running'
}

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
  const blocks = Array.isArray(item.blocks) ? item.blocks : []
  return {
    id: item.message_id,
    role: item.role,
    text: item.content,
    status: 'sent',
    blocks: blocks.length ? blocks : item.role === 'assistant'
      ? [{ type: 'text', text: item.content }]
      : [],
  }
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
    selectedSkillId: item.selected_skill_id ?? null,
    selectedSkillName: item.selected_skill_name ?? null,
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
    commandNotice: '',
    partialByRun: {} as Record<string, string>,
    partialBlocksByRun: {} as Record<string, AssistantBlock[]>,
    partialAttemptByRun: {} as Record<string, number>,
    reasoningByRun: {} as Record<string, string>,
    skillByRun: {} as Record<string, string>,
    observers: new Map<string, AbortController>(),
    slashOptions: [] as CommandOption[],
    selectedSkillId: null as string | null,
    processingByRun: {} as Record<string, ProcessingEvent[]>,
    trajectoryByRun: {} as Record<string, TrajectoryEvent[]>,
    clarificationByRun: {} as Record<string, ClarificationRequest>,
    controlLoaded: false,
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
    planWindowRunId(): string | null {
      const runs = this.active?.runs || []
      for (let index = runs.length - 1; index >= 0; index -= 1) {
        const events = this.trajectoryByRun[runs[index].runId] || []
        if (events.some(event => event.type === 'plan.created')) return runs[index].runId
      }
      return null
    },
    visibleMessages(): Message[] {
      if (!this.active) return []
      const items: Message[] = []
      
      for (const message of this.active.messages) {
        // 显示用户消息
        if (message.role === 'user') {
          items.push(message)
          
          // 查找该用户消息对应的所有 run
          const attempts = this.active.runs.filter(
            run => run.inputMessageId === message.id,
          )
          
          for (const run of attempts) {
            // 1. 显示 skill 标签（如果有）
            const skillLabel = this.skillByRun[run.runId]
            if (skillLabel) {
              items.push({
                id: `skill-${run.runId}`,
                role: 'skill',
                text: skillLabel,
                status: 'sent',
                runId: run.runId,
                skillLabel,
              })
            }
            
            // 2. 获取该 run 的所有 operations
            const events = this.processingByRun[run.runId] || []
            const trajectory = this.trajectoryByRun[run.runId] || []
            
            // 按 trajectory 顺序排序 events
            const order = new Map<string, number>()
            let next = 0
            for (const event of trajectory) {
              if (event.type === 'tool.event' && event.operationId && !order.has(event.operationId)) {
                order.set(event.operationId, next)
                next += 1
              }
            }
            const sortedEvents = [...events].sort((a, b) => {
              const ai = order.get(a.operationId) ?? Number.MAX_SAFE_INTEGER
              const bi = order.get(b.operationId) ?? Number.MAX_SAFE_INTEGER
              return ai - bi
            })
            
            // 3. thinking 活动块与 run 同生命周期：运行中「思考中」，
            //    成功后保留「思考完成」（展开看思考内容），失败/取消标红承载错误。
            items.push({
              id: `think-${run.runId}`,
              role: 'thinking',
              text: run.terminalMessage || '',
              status: !terminal.has(run.status)
                ? 'thinking'
                : run.status === 'succeeded'
                  ? 'succeeded'
                  : run.status === 'cancelled' ? 'cancelled' : 'failed',
              runId: run.runId,
              retryEligible: run.retryEligible,
              terminalMessage: run.terminalMessage,
              runFailed: run.status === 'failed',
            })

            // 3.5 M07 澄清 HITL：等待答复时在思考块后内联渲染澄清卡片。
            const clarification = this.clarificationByRun[run.runId]
            if (clarification && !terminal.has(run.status)) {
              items.push({
                id: `clarify-${run.runId}`,
                role: 'clarification',
                text: clarification.question,
                status: 'pending',
                runId: run.runId,
                clarification,
              })
            }

            // 4. 全部 operation 都渲染为工具调用节点：非终态节点承载审批等实时状态，
            //    失败信息由 tool_call 节点自身承载（徽标 + 专属文案 + 展开详情）。
            for (const event of sortedEvents) {
              const failed = isFailedOperation(event.status)
              const terminalOp = isTerminalOperation(event.status)
              items.push({
                id: `tool-call-${run.runId}-${event.operationId}`,
                role: 'tool_call',
                text: event.toolId,
                status: terminalOp
                  ? failed ? 'failed' : 'succeeded'
                  : event.status === 'awaiting_approval' ? 'pending' : 'running',
                runId: run.runId,
                operationId: event.operationId,
                toolId: event.toolId,
                argumentsSummary: event.argumentsSummary || undefined,
                resultSummary: event.resultSummary || undefined,
                elapsedMs: event.timingMs || undefined,
                toolStatus: event.status,
                errorCode: event.errorCode,
                failureLabel: failed ? operationFailureLabel(event) : undefined,
                processingEvent: event,
              })
            }

            // 5. 如果 run 还在进行中（非终态），显示流式输出
            if (!terminal.has(run.status)) {
              // 如果没有 outputMessageId，显示部分输出
              if (!run.outputMessageId) {
                const partialText = this.partialByRun[run.runId] || ''
                const partialBlocks = this.partialBlocksByRun[run.runId] || []

                // 只有在有部分输出时才显示（避免重复显示 thinking）
                if (partialText || partialBlocks.length > 0) {
                  items.push({
                    id: `partial-${run.runId}`,
                    role: 'assistant',
                    text: partialText,
                    blocks: partialBlocks,
                    status: run.cancelRequested ? 'stopping' : 'streaming',
                    runId: run.runId,
                  })
                }
              }
            } else if (run.status === 'succeeded') {
              // 6. Run 成功，显示最终的 assistant 消息（如果有 outputMessageId）
              // outputMessageId 对应的消息会在后续循环中被添加
              continue
            }
          }
        } else if (message.role === 'assistant') {
          // 显示 assistant 消息（最终答案）。
          // 思考内容统一由 think 活动块承载，这里不再重复注入 reasoning 行。
          items.push(message)
        } else {
          // 其他类型的消息直接显示
          items.push(message)
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
      this.partialBlocksByRun = {}
      this.partialAttemptByRun = {}
      this.reasoningByRun = {}
      this.skillByRun = {}
      this.commandNotice = ''
      this.selectedSkillId = null
      this.processingByRun = {}
      this.trajectoryByRun = {}
      this.clarificationByRun = {}
      this.slashOptions = []
      this.controlLoaded = false
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
      this.commandNotice = ''
      this.commandNotice = ''
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
      this.commandNotice = ''
      this.commandNotice = ''
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
          if (run.selectedSkillName) {
            this.skillByRun[run.runId] = run.selectedSkillName
          } else if (run.selectedSkillId) {
            this.skillByRun[run.runId] = run.selectedSkillId
          }
        }
        for (const message of conversation.messages) {
          if (message.role !== 'assistant') continue
          message.runId = conversation.runs.find(
            run => run.outputMessageId === message.id,
          )?.runId
        }
        for (const run of conversation.runs) {
          void this.loadProcessing(run.runId)
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
    async loadControl() {
      const ownership = useOwnershipStore()
      if (this.controlLoaded) return
      try {
        const [commandsResponse, skillsResponse] = await Promise.all([
          ownership.apiFetch('/api/commands'),
          ownership.apiFetch('/api/skills'),
        ])
        if (!commandsResponse.ok || !skillsResponse.ok) throw new Error()
        const commands = await readJson(commandsResponse)
        const skills = await readJson(skillsResponse)
        this.slashOptions = [
          ...commands.map((item: any) => ({
            id: item.command,
            label: item.command,
            detail: item.description,
            kind: 'command' as const,
            parent: item.parent,
          })),
          ...skills.map((item: any) => ({
            id: item.skill_id,
            label: item.name,
            detail: item.description,
            kind: 'skill' as const,
            skillId: item.skill_id,
            enabled: item.enabled,
            compatible: item.compatible,
          })).filter((item: any) => item.enabled !== false && item.compatible !== false),
        ]
        this.controlLoaded = true
      } catch {
        this.slashOptions = [
          { id: '/mcp', label: '/mcp', detail: '查看 MCP Server 与工具暴露状态', kind: 'command' },
          { id: '/memory', label: '/memory', detail: '查看和管理长期记忆', kind: 'command' },
        ]
        this.controlLoaded = true
      }
    },
    selectSkill(skillId: string) {
      this.selectedSkillId = skillId
    },
    clearSkill() {
      this.selectedSkillId = null
    },
    async loadProcessing(runId: string) {
      const ownership = useOwnershipStore()
      try {
        const response = await ownership.apiFetch(
          '/api/operations?run_id=' + encodeURIComponent(runId),
        )
        if (!response.ok) return
        const items = await readJson(response)
        this.processingByRun[runId] = items.map((item: any) => ({
          operationId: item.operation_id,
          toolId: item.tool_id,
          toolCallId: item.tool_call_id,
          status: item.status,
          risk: item.risk,
          errorCode: item.error_code ?? null,
          approvalId: item.approval_id,
          resultSummary: item.result_summary,
          source: item.source || 'native',
          serverId: item.server_id || null,
          argumentsSummary: item.arguments_summary || null,
          riskReason: item.risk_reason || null,
          timingMs: item.timing_ms ?? null,
          artifacts: item.artifacts || [],
        }))
        const eventResponse = await ownership.apiFetch(
          '/api/runs/' + encodeURIComponent(runId) + '/event-log',
        )
        if (eventResponse.ok) {
          const events = await readJson(eventResponse)
          let reasoningText = ''
          for (const item of events) {
            if (item.type !== 'assistant.chunk') continue
            const chunk = item.payload?.chunk || {}
            if (chunk.type === 'reasoning_delta') {
              reasoningText += String(chunk.delta || '')
            } else if (chunk.type === 'block_end' && chunk.block?.type === 'reasoning') {
              reasoningText = String(chunk.block.text || reasoningText)
            }
          }
          // 事件日志缺 reasoning 分片时保留已有内容（流式抢救或历史缓存），
          // 不用空重建覆盖。
          if (reasoningText) this.reasoningByRun[runId] = reasoningText
          this.trajectoryByRun[runId] = events
            .filter((item: any) => item.type !== 'assistant.chunk' && item.type !== 'assistant.message')
            .map(mapRunEvent)
        }
      } catch {
        this.processingByRun[runId] = this.processingByRun[runId] || []
        this.trajectoryByRun[runId] = this.trajectoryByRun[runId] || []
      }
    },
    // SSE 为唯一状态源：run_event 帧增量应用 operations/轨迹；
    // 全量 loadProcessing 只在建流前、流结束校对、历史加载与审批决定后运行。
    applyRunEvent(runId: string, data: any) {
      const type = data.type
      if (type === 'assistant.chunk' || type === 'assistant.message') return
      const payload = data.payload || {}
      const sequence = Number(data.sequence)
      if (type === 'run.waiting_approval') {
        // 审批挂起：把 approval_id 按 tool_call_id 回填到对应操作卡。
        const approvalId = payload.approval_id
        const toolCallId = payload.tool_call_id
        if (approvalId) {
          const operations = this.processingByRun[runId] || []
          this.processingByRun[runId] = operations.map(item =>
            item.approvalId
              ? item
              : toolCallId
                ? (item.toolCallId === toolCallId ? { ...item, approvalId } : item)
                : (item.status === 'awaiting_approval' ? { ...item, approvalId } : item),
          )
        }
      }
      if (type === 'run.waiting_clarification') {
        this.clarificationByRun[runId] = {
          question: String(payload.question || ''),
          options: Array.isArray(payload.options) ? payload.options.map(String) : [],
          multiSelect: payload.multi_select === true,
        }
      }
      if (type === 'tool.event') {
        this.applyToolEvent(runId, sequence, payload)
        return
      }
      if (type === 'approval.event') this.applyApprovalEvent(runId, payload)
      this.appendTrajectory(runId, mapRunEvent({ sequence, type, payload }))
    },
    async submitClarification(
      runId: string,
      answer: { selected: string[]; custom: string | null; skipped: boolean },
    ) {
      const ownership = useOwnershipStore()
      const response = await ownership.apiFetch(
        '/api/runs/' + encodeURIComponent(runId) + '/clarify',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            selected: answer.selected,
            custom: answer.custom,
            skipped: answer.skipped,
          }),
        },
      )
      const data = await readJson(response)
      if (!response.ok) throw new Error(data.error?.message || '澄清答复提交失败')
      delete this.clarificationByRun[runId]
    },
    appendTrajectory(runId: string, event: TrajectoryEvent) {
      const events = this.trajectoryByRun[runId] || []
      if (events.some(item => item.sequence === event.sequence)) return
      this.trajectoryByRun[runId] = [...events, event].sort((a, b) => a.sequence - b.sequence)
    },
    applyToolEvent(runId: string, sequence: number, payload: any) {
      const operationId = String(payload.operation_id || '')
      if (!operationId) return
      const operations = this.processingByRun[runId] || []
      const existing = operations.find(item => item.operationId === operationId)
      const merged: ProcessingEvent = {
        operationId,
        toolId: payload.tool_id ?? existing?.toolId ?? '',
        toolCallId: payload.tool_call_id ?? existing?.toolCallId ?? '',
        status: operationStatusFromKind(payload.kind, payload.status),
        risk: payload.risk ?? existing?.risk ?? '',
        errorCode: payload.error_code ?? existing?.errorCode ?? null,
        approvalId: existing?.approvalId ?? null,
        resultSummary: payload.summary ?? existing?.resultSummary ?? null,
        source: payload.source ?? existing?.source ?? '',
        serverId: payload.server_id ?? existing?.serverId ?? null,
        argumentsSummary: payload.arguments ?? existing?.argumentsSummary ?? null,
        riskReason: payload.risk_reason ?? existing?.riskReason ?? null,
        timingMs: payload.timing_ms ?? existing?.timingMs ?? null,
        artifacts: payload.artifacts ?? existing?.artifacts ?? [],
      }
      this.processingByRun[runId] = existing
        ? operations.map(item => (item.operationId === operationId ? merged : item))
        : [...operations, merged]
      this.appendTrajectory(runId, mapRunEvent({ sequence, type: 'tool.event', payload }))
    },
    applyApprovalEvent(runId: string, payload: any) {
      const approvalId = payload.approval_id
      const toolCallId = payload.tool_call_id
      if (!approvalId || !toolCallId) return
      const operations = this.processingByRun[runId] || []
      if (!operations.length) return
      this.processingByRun[runId] = operations.map(item =>
        item.toolCallId === toolCallId && !item.approvalId ? { ...item, approvalId } : item,
      )
    },
    async decideApproval(runId: string, approvalId: string, approved: boolean) {
      const ownership = useOwnershipStore()
      const response = await ownership.apiFetch(
        '/api/approvals/' + encodeURIComponent(approvalId) + '/decide',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            approved,
            rejected_reason: approved ? null : '用户拒绝',
          }),
        },
      )
      const data = await readJson(response)
      if (!response.ok) throw new Error(data.error?.message || '审批操作失败')
      await this.loadProcessing(runId)
    },
    async send(text: string, skillId?: string | null) {
      const conversation = this.active
      if (!conversation || this.readOnly || this.busy || !text.trim()) return
      const ownership = useOwnershipStore()
      try {
        const response = await ownership.apiFetch(
          '/api/conversations/' + encodeURIComponent(conversation.conversationId) + '/runs',
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              message: text,
              client_request_id: crypto.randomUUID(),
              selected_skill_id: skillId || null,
            }),
          },
        )
        const data = await readJson(response)
        if (!response.ok) throw new Error(data.error?.message)
        if (data.kind === 'memory_command' || data.kind === 'mcp_command' || data.kind === 'command' || data.kind === 'rag_command') {
          this.commandNotice = data.message
          this.notice = ''
          this.selectedSkillId = null
          return
        }
        const message = mapMessage(data.input_message)
        if (!conversation.messages.some(item => item.id === message.id)) conversation.messages.push(message)
        const run = mapRun(data.run)
        this.upsertRun(conversation, run)
        const skillLabel = skillId
          ? (this.slashOptions.find(option => option.skillId === skillId)?.label || skillId)
          : ''
        if (skillLabel) this.skillByRun[run.runId] = skillLabel
        this.selectedSkillId = null
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
      if (run.selectedSkillName) {
        this.skillByRun[run.runId] = run.selectedSkillName
      } else if (run.selectedSkillId) {
        this.skillByRun[run.runId] = run.selectedSkillId
      }
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
      void this.loadProcessing(runId)
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
        void this.loadProcessing(runId)
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
        if (data.version >= 3) return
        const run = this.conversations
          .flatMap(conversation => conversation.runs)
          .find(item => item.runId === runId)
        if (run?.cancelRequested) return
        this.partialByRun[runId] = (this.partialByRun[runId] || '') + (data.content || '')
        this.partialBlocksByRun[runId] = [{ type: 'text', text: this.partialByRun[runId] }]
      } else if (event === 'assistant_chunk') {
        this.consumeAssistantChunk(runId, data)
      } else if (event === 'run_event') {
        this.applyRunEvent(runId, data)
      } else if (event === 'tool' || event === 'approval') {
        // run_event 帧的同源双份编码（后端对同一条 RunEvent 各发一帧）：
        // 增量状态统一由 run_event 帧应用，跳过以避免重复处理
      } else if (event === 'snapshot') {
        this.applyRun(mapRun(data.run))
      }
    },
    consumeAssistantChunk(runId: string, data: any) {
      const chunk = data.chunk || {}
      const attempt = Number(data.execution_attempt || 0)
      if (attempt && this.partialAttemptByRun[runId] !== attempt) {
        this.partialAttemptByRun[runId] = attempt
        this.partialBlocksByRun[runId] = []
        this.partialByRun[runId] = ''
      }
      const blocks = [...(this.partialBlocksByRun[runId] || [])]
      const index = Number(chunk.index)
      if (!Number.isInteger(index) || index < 0) return
      while (blocks.length <= index) blocks.push({ type: 'text', text: '' })
      if (chunk.type === 'block_start') {
        blocks[index] = {
          type: chunk.block_type === 'reasoning' ? 'reasoning' : 'text',
          text: '',
        }
      } else if (chunk.type === 'text_delta' || chunk.type === 'reasoning_delta') {
        blocks[index] = {
          ...blocks[index],
          type: chunk.type === 'reasoning_delta' ? 'reasoning' : 'text',
          text: blocks[index].text + String(chunk.delta || ''),
        }
      } else if (chunk.type === 'block_end' && chunk.block) {
        blocks[index] = {
          type: chunk.block.type === 'reasoning' ? 'reasoning' : 'text',
          text: String(chunk.block.text || ''),
        }
      }
      this.partialBlocksByRun[runId] = blocks.filter(item => item.text || item.type === 'reasoning')
      this.partialByRun[runId] = this.partialBlocksByRun[runId]
        .filter(item => item.type === 'text')
        .map(item => item.text)
        .join('')
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
      if (run.selectedSkillName) {
        this.skillByRun[run.runId] = run.selectedSkillName
      } else if (run.selectedSkillId) {
        this.skillByRun[run.runId] = run.selectedSkillId
      }
      if (terminal.has(run.status)) {
        delete this.clarificationByRun[run.runId]
        // 终态清空流式缓存前，抢救已流出的 reasoning 内容，
        // 避免最终消息 blocks 缺 reasoning 块时 Think 内容丢失。
        const salvaged = (this.partialBlocksByRun[run.runId] || [])
          .filter(block => block.type === 'reasoning')
          .map(block => block.text)
          .join('\n\n')
        if (salvaged && !this.reasoningByRun[run.runId]) {
          this.reasoningByRun[run.runId] = salvaged
        }
        delete this.partialByRun[run.runId]
        delete this.partialBlocksByRun[run.runId]
        delete this.partialAttemptByRun[run.runId]
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
      this.partialBlocksByRun = {}
      this.partialAttemptByRun = {}
      this.reasoningByRun = {}
      this.skillByRun = {}
      this.clarificationByRun = {}
    },
  },
})
