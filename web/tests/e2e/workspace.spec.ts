import { expect, test, type Page } from '@playwright/test'

type Turn = { turn_id: string; client_message_id: string; sequence: number; user_content: string; assistant_content: string; committed_at: string }
type Thread = { thread_id: string; owner_id: string; title: string; title_source: 'auto' | 'manual'; created_at: string; updated_at: string; turns: Turn[] }
type StreamOutcome = 'completed' | 'error' | 'cancelled' | 'disconnect' | 'eof'
type OperationRecord = {
  operation_id: string
  tool_id: string
  tool_call_id: string
  status: string
  risk: string
  error_code?: string | null
  approval_id?: string | null
  result_summary?: string | null
  source?: string
  server_id?: string | null
  arguments_summary?: string | null
  risk_reason?: string | null
  timing_ms?: number | null
  artifacts?: string[]
}
type ActorIdentity = ReturnType<typeof identity>
type IdentityState = { actor: ActorIdentity }
type Backend = { threads: Thread[]; next: number; outcomes?: Record<string, StreamOutcome[]>; answers?: Record<string, string>; delays?: Record<string, number>; runInfo?: Map<string, { thread_id: string; message: string; client_message_id: string; status?: string; terminal_message?: string | null; retry_eligible?: boolean; output_message_id?: string | null }>; operations?: Record<string, OperationRecord[]>; nextRunOperations?: OperationRecord[]; requestCounts?: Record<string, number> }
type ControlledStream = {
  waitForRequest: () => Promise<{ run_id: string; thread_id: string; message: string; client_message_id: string }>
  emit: (event: 'started' | 'token' | 'completed' | 'error' | 'cancelled' | 'runEvent', payload?: Record<string, unknown>) => void
}

const now = () => new Date().toISOString()
const identity = (kind: 'guest' | 'user' | 'temporary_guest', owner: string, username?: string) => ({
  actor: { kind, owner_id: owner, username: username || null },
  access_token: `${kind}-access-token`,
  access_expires_at: new Date(Date.now() + 900_000).toISOString(),
  mode: kind === 'temporary_guest' ? 'temporary' : 'durable',
})

async function installControlledStream(page: Page, backend: Backend): Promise<ControlledStream> {
  type StreamRequest = { run_id: string; thread_id: string; message: string; client_message_id: string }
  let request: StreamRequest | undefined
  let resolveChunk: ((value: string | null) => void) | undefined
  const queuedChunks: Array<string | null> = []
  const requestWaiters: Array<(value: StreamRequest) => void> = []
  const pendingRequests: StreamRequest[] = []
  backend.runInfo = new Map()

  const pushRequest = (value: StreamRequest) => {
    request = value
    const waiter = requestWaiters.shift()
    if (waiter) waiter(value)
    else pendingRequests.push(value)
  }

  await page.exposeFunction('__venagentControlledStreamRequest', (value: { run_id: string }) => {
    const info = backend.runInfo?.get(value.run_id)
    if (!info) throw new Error(`unknown run for controlled stream: ${value.run_id}`)
    pushRequest({ run_id: value.run_id, ...info })
  })
  await page.exposeFunction('__venagentControlledStreamNext', () => new Promise<string | null>(resolve => {
    const chunk = queuedChunks.shift()
    if (chunk !== undefined) resolve(chunk)
    else resolveChunk = resolve
  }))
  await page.addInitScript(() => {
    const originalFetch = window.fetch.bind(window)
    window.fetch = async (input, init) => {
      const url = new URL(input instanceof Request ? input.url : String(input), window.location.href)
      const match = url.pathname.match(/^\/api\/runs\/([^/]+)\/events$/)
      if (!match) return originalFetch(input, init)
      const controls = window as typeof window & {
        __venagentControlledStreamRequest: (value: unknown) => Promise<void>
        __venagentControlledStreamNext: () => Promise<string | null>
      }
      await controls.__venagentControlledStreamRequest({ run_id: match[1] })
      const encoder = new TextEncoder()
      const stream = new ReadableStream<Uint8Array>({
        async pull(controller) {
          const chunk = await controls.__venagentControlledStreamNext()
          if (chunk === null) controller.close()
          else controller.enqueue(encoder.encode(chunk))
        },
      })
      return new Response(stream, { headers: { 'Content-Type': 'text/event-stream' } })
    }
  })

  return {
    waitForRequest: () => new Promise<StreamRequest>(resolve => {
      const pending = pendingRequests.shift()
      if (pending) resolve(pending)
      else requestWaiters.push(resolve)
    }),
    emit(event, payload = {}) {
      if (!request) throw new Error('controlled stream request has not started')
      const runId = request.run_id
      if (event === 'runEvent') {
        const runEvent = `event: run_event\ndata: ${JSON.stringify({ version: 3, run_id: runId, sequence: Number(payload.sequence), type: payload.type, payload: payload.payload || {}, created_at: now() })}\n\n`
        if (resolveChunk) {
          const resolve = resolveChunk
          resolveChunk = undefined
          resolve(runEvent)
        } else {
          queuedChunks.push(runEvent)
        }
        return
      }
      const sequence = event === 'started' ? 1 : event === 'token' ? 2 : 3
      if (event === 'completed' || event === 'error' || event === 'cancelled') {
        const thread = backend.threads.find(item => item.thread_id === request?.thread_id)
        if (event === 'completed' && thread && !thread.turns.some(turn => turn.client_message_id === request?.client_message_id)) {
          thread.turns.push({
            turn_id: `turn-${thread.turns.length + 1}`,
            client_message_id: request.client_message_id,
            sequence: thread.turns.length + 1,
            user_content: request.message,
            assistant_content: String(payload.answer || ''),
            committed_at: now(),
          })
          thread.updated_at = now()
        }
        const terminal = event === 'completed'
          ? {
              run_id: runId,
              conversation_id: request.thread_id,
              input_message_id: `input-${runId}`,
              output_message_id: `output-${runId}`,
              status: 'succeeded',
              phase: 'completed',
              terminal_message: null,
              cancel_requested_at: null,
              retry_eligible: false,
            }
          : event === 'cancelled'
            ? {
                run_id: runId,
                conversation_id: request.thread_id,
                input_message_id: `input-${runId}`,
                output_message_id: null,
                status: 'cancelled',
                phase: 'cancelled',
                terminal_message: String(payload.terminal_message || '已取消'),
                cancel_requested_at: null,
                retry_eligible: true,
              }
            : {
                run_id: runId,
                conversation_id: request.thread_id,
                input_message_id: `input-${runId}`,
                output_message_id: null,
                status: 'failed',
                phase: 'failed',
                terminal_message: String(payload.terminal_message || '运行失败'),
                cancel_requested_at: null,
                retry_eligible: true,
              }
        const info = backend.runInfo?.get(runId)
        if (info) {
          info.status = terminal.status
          info.terminal_message = terminal.terminal_message
          info.retry_eligible = terminal.retry_eligible
          info.output_message_id = terminal.output_message_id
        }
        const runEvent = event === 'completed' ? '' : `event: run_event\ndata: ${JSON.stringify({ version: 3, run_id: runId, sequence, type: event === 'cancelled' ? 'run.cancelled' : 'run.failed', payload: {}, created_at: now() })}\n\n`
        const chunk = runEvent + `event: snapshot\ndata: ${JSON.stringify({ run_id: runId, run: terminal })}\n\n`
        if (resolveChunk) {
          const resolve = resolveChunk
          resolveChunk = undefined
          resolve(chunk)
        } else {
          queuedChunks.push(chunk)
        }
        queuedChunks.push(null)
        return
      }
      const data = { version: 1, sequence, thread_id: request.thread_id, run_id: runId, ...payload }
      const chunk = `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`
      if (resolveChunk) {
        const resolve = resolveChunk
        resolveChunk = undefined
        resolve(chunk)
      } else {
        queuedChunks.push(chunk)
      }
    },
  }
}

async function mockBackend(page: Page, backend: Backend, mode: 'temporary' | 'durable' = 'temporary', sharedIdentity?: IdentityState) {
  let actor = mode === 'temporary' ? identity('temporary_guest', 'temp-1') : identity('guest', 'guest-1')
  const currentActor = () => sharedIdentity?.actor || actor
  const setActor = (next: ActorIdentity) => {
    if (sharedIdentity) sharedIdentity.actor = next
    else actor = next
  }
  const threadToConversation = (thread: Thread) => {
    const messages: Array<Record<string, unknown>> = []
    const runs: Array<Record<string, unknown>> = []
    for (const turn of thread.turns) {
      const inputId = `input-${thread.thread_id}-${turn.sequence}`
      const outputId = `output-${thread.thread_id}-${turn.sequence}`
      messages.push({ message_id: inputId, role: 'user', content: turn.user_content, created_at: turn.committed_at })
      messages.push({ message_id: outputId, role: 'assistant', content: turn.assistant_content, created_at: turn.committed_at })
      const runId = `run-${thread.thread_id}-${turn.sequence}`
      runs.push({
        run_id: runId,
        conversation_id: thread.thread_id,
        input_message_id: inputId,
        output_message_id: outputId,
        status: 'succeeded',
        phase: 'completed',
        terminal_message: null,
        cancel_requested_at: null,
        retry_eligible: false,
      })
    }
    for (const [runId, info] of backend.runInfo || []) {
      if (info.thread_id !== thread.thread_id) continue
      if (runs.some(run => run.run_id === runId)) continue
      const status = info.status || 'running'
      const turn = thread.turns.find(item => item.client_message_id === info.client_message_id)
      const inputId = `input-${runId}`
      const outputId = info.output_message_id || `output-${runId}`
      if (!(status === 'succeeded' && turn) && !messages.some(message => message.message_id === inputId)) {
        messages.push({ message_id: inputId, role: 'user', content: info.message, created_at: now() })
      }
      runs.push({
        run_id: runId,
        conversation_id: thread.thread_id,
        input_message_id: inputId,
        output_message_id: status === 'succeeded' ? outputId : null,
        status,
        phase: status,
        terminal_message: info.terminal_message || null,
        cancel_requested_at: null,
        retry_eligible: info.retry_eligible || false,
      })
    }
    return {
      conversation_id: thread.thread_id,
      owner_id: thread.owner_id,
      title: thread.title,
      title_source: thread.title_source,
      created_at: thread.created_at,
      updated_at: thread.updated_at,
      messages,
      runs,
    }
  }

  await page.exposeFunction('__venagentAutoStreamPlan', (runId: string) => {
    const info = backend.runInfo?.get(runId)
    if (!info) return []
    const thread = backend.threads.find(item => item.thread_id === info.thread_id)
    if (!thread) return []
    const outcome = backend.outcomes?.[info.message]?.shift() || 'completed'
    const answer = backend.answers?.[info.message] || `回复：${info.message}`
    const partial = outcome === 'completed' ? answer : `部分回复：${info.message}`
    const running = { run_id: runId, conversation_id: thread.thread_id, input_message_id: `input-${runId}`, output_message_id: null, status: 'running', phase: 'running', terminal_message: null, cancel_requested_at: null, retry_eligible: false }
    const snapshot = (run: Record<string, unknown>) => `event: snapshot\ndata: ${JSON.stringify({ run_id: runId, run })}\n\n`
    const token = `event: token\ndata: ${JSON.stringify({ version: 3, run_id: runId, content: partial })}\n\n`
    if (outcome === 'completed') {
      if (!thread.turns.some(turn => turn.client_message_id === info.client_message_id)) {
        thread.turns.push({ turn_id: `turn-${thread.turns.length + 1}`, client_message_id: info.client_message_id, sequence: thread.turns.length + 1, user_content: info.message, assistant_content: answer, committed_at: now() })
        if (thread.title_source === 'auto' && thread.title === '新对话') thread.title = info.message.slice(0, 28)
        thread.updated_at = now()
      }
      const succeeded = { ...running, output_message_id: `output-${runId}`, status: 'succeeded', phase: 'completed' }
      if (info) {
        info.status = succeeded.status
        info.terminal_message = null
        info.retry_eligible = false
        info.output_message_id = succeeded.output_message_id
      }
      return [snapshot(running), token, snapshot(succeeded)]
    }
    const terminal = outcome === 'cancelled'
      ? { ...running, status: 'cancelled', phase: 'cancelled', terminal_message: '已停止生成' }
      : { ...running, status: 'failed', phase: 'failed', terminal_message: outcome === 'disconnect' ? '连接已中断' : '发送失败', retry_eligible: true }
    if (info) {
      info.status = terminal.status
      info.terminal_message = terminal.terminal_message
      info.retry_eligible = terminal.retry_eligible
      info.output_message_id = terminal.output_message_id
    }
    return [snapshot(running), token, snapshot(terminal)]
  })
  await page.addInitScript(() => {
    const originalFetch = window.fetch.bind(window)
    window.fetch = async (input, init) => {
      const url = new URL(input instanceof Request ? input.url : String(input), window.location.href)
      const match = url.pathname.match(/^\/api\/runs\/([^/]+)\/events$/)
      if (!match) return originalFetch(input, init)
      const controls = window as typeof window & {
        __venagentAutoStreamPlan: (runId: string) => Promise<string[]>
      }
      const plan = await controls.__venagentAutoStreamPlan(match[1])
      const encoder = new TextEncoder()
      const stream = new ReadableStream<Uint8Array>({
        async pull(controller) {
          if (plan.length === 0) {
            controller.close()
            return
          }
          const chunk = plan.shift()!
          await new Promise(resolve => setTimeout(resolve, 300))
          controller.enqueue(encoder.encode(chunk))
        },
      })
      return new Response(stream, { headers: { 'Content-Type': 'text/event-stream' } })
    }
  })

  await page.route('**/health', route => route.fulfill({ json: {
    status: 'ok', mode: currentActor().mode,
    capabilities: { chat: 'available', anonymous_chat: 'available', account_identity: mode === 'durable' ? 'available' : 'unavailable', conversation_persistence: mode === 'durable' ? 'available' : 'unavailable' },
  } }))
  await page.route('**/api/**', async route => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname
    const method = request.method()
    if (path === '/api/auth/refresh' || path === '/api/auth/guest') return route.fulfill({ json: currentActor() })
    if (path === '/api/auth/login' || path === '/api/auth/register') {
      if (mode === 'temporary') return route.fulfill({ status: 503, json: { error: { code: 'account_service_unavailable', message: '持久化当前不可用，账号操作未执行' } } })
      const next = identity('user', 'user-1', 'alice')
      setActor(next)
      return route.fulfill({ status: path.endsWith('register') ? 201 : 200, json: next })
    }
    if (path === '/api/auth/logout') {
      const next = identity('guest', 'guest-new')
      setActor(next)
      return route.fulfill({ json: next })
    }
    if (path === '/api/auth/password') return route.fulfill({ json: currentActor() })
    if (path === '/api/auth/account') {
      const next = identity('guest', 'guest-after-delete')
      setActor(next)
      return route.fulfill({ status: 202, json: { status: 'account_deletion_started' } })
    }
    const ownerThreads = () => backend.threads.filter(thread => thread.owner_id === currentActor().actor.owner_id)
    if (path === '/api/conversations' && method === 'GET') return route.fulfill({ json: {
      items: ownerThreads().map(thread => {
        const { turns: _turns, owner_id: _owner_id, ...summary } = threadToConversation(thread)
        return summary
      }),
      next_cursor: null,
    } })
    if (path === '/api/conversations' && method === 'POST') {
      const id = `00000000-0000-0000-0000-${String(++backend.next).padStart(12, '0')}`
      const thread: Thread = { thread_id: id, owner_id: currentActor().actor.owner_id, title: '新对话', title_source: 'auto', created_at: now(), updated_at: now(), turns: [] }
      backend.threads.push(thread)
      return route.fulfill({ status: 201, json: threadToConversation(thread) })
    }
    const conversationId = path.match(/^\/api\/conversations\/([^/]+)$/)?.[1]
    if (conversationId) {
      const thread = backend.threads.find(item => item.thread_id === conversationId && item.owner_id === currentActor().actor.owner_id)
      if (!thread) return route.fulfill({ status: 404, json: { error: { code: 'conversation_not_found', message: '对话不存在' } } })
      if (method === 'GET') return route.fulfill({ json: threadToConversation(thread) })
      if (method === 'PATCH') {
        const body = request.postDataJSON()
        thread.title = body.title.trim()
        thread.title_source = 'manual'
        thread.updated_at = now()
        return route.fulfill({ json: threadToConversation(thread) })
      }
      if (method === 'DELETE') {
        backend.threads.splice(backend.threads.indexOf(thread), 1)
        return route.fulfill({ status: 204 })
      }
    }
    const approvalDecision = path.match(/^\/api\/approvals\/([^/]+)\/decide$/)
    if (approvalDecision && method === 'POST') {
      const approved = request.postDataJSON()?.approved === true
      for (const ops of Object.values(backend.operations || {})) {
        for (const op of ops) {
          if (op.approval_id === approvalDecision[1]) {
            op.status = approved ? 'succeeded' : 'rejected'
            op.result_summary = approved ? '已批准执行完成' : '用户在审批中拒绝该命令'
          }
        }
      }
      return route.fulfill({ json: { approval_id: approvalDecision[1], status: approved ? 'approved' : 'rejected' } })
    }
    const runCreation = path.match(/^\/api\/conversations\/([^/]+)\/runs$/)
    if (runCreation && method === 'POST') {
      const body = request.postDataJSON()
      const thread = backend.threads.find(item => item.thread_id === runCreation[1] && item.owner_id === currentActor().actor.owner_id)
      if (!thread) return route.fulfill({ status: 404, json: { error: { code: 'conversation_not_found', message: '对话不存在' } } })
      const runId = `run-${runCreation[1]}-${thread.turns.length + 1}-${Date.now()}`
      const inputMessageId = `input-${runId}`
      backend.runInfo = backend.runInfo || new Map()
      backend.runInfo.set(runId, { thread_id: thread.thread_id, message: body.message, client_message_id: body.client_request_id, status: 'running', retry_eligible: false, output_message_id: null })
      if (backend.nextRunOperations?.length) {
        backend.operations = backend.operations || {}
        backend.operations[runId] = backend.nextRunOperations
        backend.nextRunOperations = []
      }
      const run = {
        run_id: runId,
        conversation_id: thread.thread_id,
        input_message_id: inputMessageId,
        output_message_id: null,
        status: 'running',
        phase: 'running',
        terminal_message: null,
        cancel_requested_at: null,
        retry_eligible: false,
      }
      return route.fulfill({ status: 202, json: {
        run,
        input_message: { message_id: inputMessageId, role: 'user', content: body.message },
      } })
    }
    const runIdMatch = path.match(/^\/api\/runs\/([^/]+)$/)
    if (runIdMatch && method === 'GET') {
      const runId = runIdMatch[1]
      const info = backend.runInfo?.get(runId)
      const thread = info ? backend.threads.find(item => item.thread_id === info.thread_id) : undefined
      if (!thread) return route.fulfill({ status: 404, json: { error: { code: 'run_not_found', message: '运行不存在' } } })
      const turn = thread.turns.find(item => item.client_message_id === info?.client_message_id)
      const outcome = backend.outcomes?.[info?.message || '']?.shift()
      const run = {
        run_id: runId,
        conversation_id: thread.thread_id,
        input_message_id: `input-${runId}`,
        output_message_id: turn ? `output-${runId}` : null,
        status: turn ? 'succeeded' : outcome === 'disconnect' ? 'failed' : outcome === 'cancelled' ? 'cancelled' : outcome === 'error' ? 'failed' : 'running',
        phase: turn ? 'completed' : outcome === 'disconnect' ? 'failed' : outcome === 'cancelled' ? 'cancelled' : outcome === 'error' ? 'failed' : 'running',
        terminal_message: outcome === 'disconnect' ? '连接已中断' : outcome === 'error' ? '发送失败' : null,
        cancel_requested_at: null,
        retry_eligible: true,
      }
      return route.fulfill({ json: run })
    }
    const eventsMatch = path.match(/^\/api\/runs\/([^/]+)\/events$/)
    if (eventsMatch) {
      const runId = eventsMatch[1]
      const info = backend.runInfo?.get(runId)
      const thread = info ? backend.threads.find(item => item.thread_id === info.thread_id) : undefined
      if (!thread || !info) return route.fulfill({ status: 404, json: { error: { code: 'run_not_found', message: '运行不存在' } } })
      const outcome = backend.outcomes?.[info.message]?.shift() || 'completed'
      if (outcome === 'disconnect') return route.abort('connectionfailed')
      const answer = backend.answers?.[info.message] || `回复：${info.message}`
      const partial = outcome === 'completed' ? answer : `部分回复：${info.message}`
      const inputId = `input-${runId}`
      const outputId = `output-${runId}`
      const running = { run_id: runId, conversation_id: thread.thread_id, input_message_id: inputId, output_message_id: null, status: 'running', phase: 'running', terminal_message: null, cancel_requested_at: null, retry_eligible: false }
      const snapshot = (run: Record<string, unknown>) => `event: snapshot\ndata: ${JSON.stringify({ run_id: runId, run })}\n\n`
      const token = `event: token\ndata: ${JSON.stringify({ version: 3, run_id: runId, content: partial })}\n\n`
      if (outcome === 'completed') {
        if (!thread.turns.some(turn => turn.client_message_id === info.client_message_id)) {
          thread.turns.push({ turn_id: `turn-${thread.turns.length + 1}`, client_message_id: info.client_message_id, sequence: thread.turns.length + 1, user_content: info.message, assistant_content: answer, committed_at: now() })
          if (thread.title_source === 'auto' && thread.title === '新对话') thread.title = info.message.slice(0, 28)
          thread.updated_at = now()
        }
        const succeeded = { ...running, output_message_id: outputId, status: 'succeeded', phase: 'completed' }
        return route.fulfill({ contentType: 'text/event-stream', body: snapshot(running) + token + snapshot(succeeded) })
      }
      const terminal = outcome === 'cancelled'
        ? { ...running, status: 'cancelled', phase: 'cancelled', terminal_message: '已停止生成' }
        : { ...running, status: 'failed', phase: 'failed', terminal_message: '发送失败', retry_eligible: true }
      const failedEvent = `event: run_event\ndata: ${JSON.stringify({ version: 3, run_id: runId, sequence: 2, type: outcome === 'cancelled' ? 'run.cancelled' : 'run.failed', payload: {}, created_at: now() })}\n\n`
      return route.fulfill({ contentType: 'text/event-stream', body: snapshot(running) + token + failedEvent + snapshot(terminal) })
    }
    const retryMatch = path.match(/^\/api\/runs\/([^/]+)\/retry$/)
    if (retryMatch && method === 'POST') {
      const sourceRunId = retryMatch[1]
      const info = backend.runInfo?.get(sourceRunId)
      const thread = info ? backend.threads.find(item => item.thread_id === info.thread_id) : undefined
      if (!thread || !info) return route.fulfill({ status: 404, json: { error: { code: 'run_not_found', message: '运行不存在' } } })
      const runId = `retry-${sourceRunId}-${Date.now()}`
      backend.runInfo = backend.runInfo || new Map()
      const body = request.postDataJSON()
      backend.runInfo.set(runId, { thread_id: thread.thread_id, message: info.message, client_message_id: body.client_request_id || info.client_message_id, status: 'running', retry_eligible: false, output_message_id: null })
      const run = {
        run_id: runId,
        conversation_id: thread.thread_id,
        input_message_id: `input-${runId}`,
        output_message_id: null,
        status: 'running',
        phase: 'running',
        terminal_message: null,
        cancel_requested_at: null,
        retry_eligible: false,
      }
      return route.fulfill({ json: { run } })
    }
    if (path.includes('/cancel')) return route.fulfill({ status: 202, json: { status: 'cancel_requested' } })
    if (path.endsWith('/event-log')) {
      backend.requestCounts = backend.requestCounts || {}
      backend.requestCounts['event-log'] = (backend.requestCounts['event-log'] || 0) + 1
      return route.fulfill({ json: [] })
    }
    if (path === '/api/operations') {
      backend.requestCounts = backend.requestCounts || {}
      backend.requestCounts['operations'] = (backend.requestCounts['operations'] || 0) + 1
      const runId = url.searchParams.get('run_id') || ''
      return route.fulfill({ json: backend.operations?.[runId] || [] })
    }
    if (path === '/api/commands') return route.fulfill({ json: [] })
    if (path === '/api/skills') return route.fulfill({ json: [] })
    return route.fulfill({ status: 404, json: { error: { code: 'not_found', message: 'not found' } } })
  })
}

test('temporary anonymous mode chats and explains unavailable account actions', async ({ page }) => {
  const backend = { threads: [], next: 0 }
  await mockBackend(page, backend)
  await page.goto('/')
  await expect(page.getByText('临时匿名').first()).toBeVisible()
  await page.getByLabel('输入消息').fill('你好')
  await page.getByLabel('发送').click()
  await expect(page.getByText('回复：你好')).toBeVisible()
  await page.getByRole('button', { name: '登录' }).click()
  await expect(page.getByRole('dialog', { name: '账号功能暂不可用' })).toContainText('账号操作没有执行')
  await expect(page.getByRole('dialog')).toContainText('服务重启后内容可能丢失')
})

test('legacy browser-only history is removed instead of being exposed', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('venagent-conversations-v1', JSON.stringify({
    version: 1, activeId: 'old-thread', conversations: [{ threadId: 'old-thread', title: '旧对话', expired: false, updatedAt: Date.now(), messages: [{ id: 'm1', role: 'user', text: '旧消息', status: 'sent' }] }],
  })))
  await mockBackend(page, { threads: [], next: 0 })
  await page.goto('/')
  await expect(page.getByText('旧对话')).toHaveCount(0)
  expect(await page.evaluate(() => localStorage.getItem('venagent-conversations-v1'))).toBeNull()
})

test('account history restores across two isolated browser contexts', async ({ browser }) => {
  const backend: Backend = { threads: [], next: 0 }
  const firstContext = await browser.newContext()
  const secondContext = await browser.newContext()
  const first = await firstContext.newPage()
  const second = await secondContext.newPage()
  await mockBackend(first, backend, 'durable')
  await mockBackend(second, backend, 'durable')

  await first.goto('/')
  await first.getByRole('button', { name: '登录' }).click()
  await first.getByLabel('用户名').fill('alice')
  await first.getByLabel('密码').fill('password-123')
  await first.getByRole('dialog').getByRole('button', { name: '确认' }).click()
  await first.getByLabel('输入消息').fill('跨浏览器消息')
  await first.getByLabel('发送').click()
  await expect(first.getByText('回复：跨浏览器消息')).toBeVisible()

  await second.goto('/')
  await second.getByRole('button', { name: '登录' }).click()
  await second.getByLabel('用户名').fill('alice')
  await second.getByLabel('密码').fill('password-123')
  await second.getByRole('dialog').getByRole('button', { name: '确认' }).click()
  await expect(second.getByText('跨浏览器消息').first()).toBeVisible()
  await second.getByText('跨浏览器消息').first().click()
  await expect(second.getByText('回复：跨浏览器消息')).toBeVisible()

  await firstContext.close()
  await secondContext.close()
})

test('manual rename is optimistic and remains in server history', async ({ page }) => {
  const backend: Backend = { threads: [], next: 0 }
  await mockBackend(page, backend, 'durable')
  await page.goto('/')
  await page.getByRole('button', { name: '登录' }).click()
  await page.getByLabel('用户名').fill('alice')
  await page.getByLabel('密码').fill('password-123')
  await page.getByRole('dialog').getByRole('button', { name: '确认' }).click()
  await page.getByRole('button', { name: /重命名 新对话/ }).click()
  const title = page.getByLabel('对话标题')
  await title.fill('我的新标题')
  await title.press('Enter')
  await expect(page.getByText('我的新标题').first()).toBeVisible()
  expect(backend.threads.find(thread => thread.owner_id === 'user-1')?.title).toBe('我的新标题')
})

test('failed partial shows partial then retry commits one pair', async ({ page }) => {
  const backend: Backend = { threads: [], next: 0 }
  await mockBackend(page, backend, 'durable')
  const stream = await installControlledStream(page, backend)
  await page.goto('/')

  await page.getByLabel('输入消息').fill('失败 A')
  await page.getByLabel('发送').click()
  await stream.waitForRequest()
  stream.emit('started')
  stream.emit('token', { content: '部分回复：失败 A' })
  await expect(page.getByText('部分回复：失败 A')).toBeVisible()
  stream.emit('error')
  await expect(page.getByText('运行失败').first()).toBeVisible()
  await expect(page.getByRole('button', { name: '重试' })).toBeVisible()

  await page.getByRole('button', { name: '重试' }).click()
  await stream.waitForRequest()
  stream.emit('started')
  stream.emit('token', { content: '回复：失败 A' })
  stream.emit('completed', { answer: '回复：失败 A' })
  await expect(page.getByText('回复：失败 A', { exact: true })).toBeVisible()
  expect(backend.threads[0].turns).toHaveLength(1)
  // 完成后 think 块保留为「思考完成」，可展开查看思考内容（无内容时显示占位）
  const doneThink = page.locator('.think-block').filter({ hasText: '思考完成' })
  await expect(doneThink).toHaveCount(1)
  await doneThink.locator('.think-head').click()
  await expect(doneThink.locator('.think-details')).toContainText('本次运行没有返回思考内容')
})

test('cancelled partial shows partial then cancelled state', async ({ page }) => {
  const backend: Backend = { threads: [], next: 0 }
  await mockBackend(page, backend, 'durable')
  const stream = await installControlledStream(page, backend)
  await page.goto('/')

  await page.getByLabel('输入消息').fill('取消消息')
  await page.getByLabel('发送').click()
  await stream.waitForRequest()
  stream.emit('started')
  stream.emit('token', { content: '部分回复：取消消息' })
  await expect(page.getByText('部分回复：取消消息')).toBeVisible()
  stream.emit('cancelled')
  await expect(page.getByText('已取消').first()).toBeVisible()
  expect(backend.threads[0].turns).toHaveLength(0)
})

test('stopping before started keeps the user message and marks assistant cancelled', async ({ page }) => {
  const backend: Backend = { threads: [], next: 0 }
  await mockBackend(page, backend, 'durable')
  const stream = await installControlledStream(page, backend)
  await page.goto('/')

  await page.getByLabel('输入消息').fill('立即停止')
  await page.getByLabel('发送').click()
  await stream.waitForRequest()
  stream.emit('started')
  await page.getByLabel('停止生成').click()
  stream.emit('cancelled')
  await expect(page.getByText('立即停止', { exact: true })).toBeVisible()
  await expect(page.getByText('已取消').first()).toBeVisible()
  expect(backend.threads[0].turns).toHaveLength(0)
})

test('failed stream is labelled failed and retryable', async ({ page }) => {
  const backend: Backend = { threads: [], next: 0 }
  await mockBackend(page, backend, 'durable')
  const stream = await installControlledStream(page, backend)
  await page.goto('/')

  await page.getByLabel('输入消息').fill('网络中断')
  await page.getByLabel('发送').click()
  await stream.waitForRequest()
  stream.emit('started')
  stream.emit('token', { content: '部分回复：网络中断' })
  await expect(page.getByText('部分回复：网络中断')).toBeVisible()
  stream.emit('error')
  await expect(page.getByText('运行失败').first()).toBeVisible()
  await expect(page.getByRole('button', { name: '重试' })).toBeVisible()
  expect(backend.threads[0].turns).toHaveLength(0)
})

test('conversation_not_found removes the local reference and leaves read-only state', async ({ page }) => {
  const backend: Backend = { threads: [], next: 0 }
  await mockBackend(page, backend, 'durable')
  const created = page.waitForResponse(response =>
    new URL(response.url()).pathname === '/api/conversations' && response.request().method() === 'POST',
  )
  await page.goto('/')
  await created
  const missingTitle = backend.threads[0].title
  backend.threads.splice(0)

  await page.getByText(missingTitle, { exact: true }).first().click()
  await expect(page.getByLabel('输入消息')).toBeDisabled()
  expect(backend.threads).toHaveLength(0)
})

test('cross-tab logout hides the previous owner content before guest refresh', async ({ browser }) => {
  const backend: Backend = { threads: [], next: 0 }
  const firstContext = await browser.newContext()
  const secondContext = await browser.newContext()
  const first = await firstContext.newPage()
  const second = await secondContext.newPage()
  await mockBackend(first, backend, 'durable')
  await mockBackend(second, backend, 'durable')

  await first.goto('/')
  await first.getByRole('button', { name: '登录' }).click()
  await first.getByLabel('用户名').fill('alice')
  await first.getByLabel('密码').fill('password-123')
  await first.getByRole('dialog').getByRole('button', { name: '确认' }).click()
  await first.getByLabel('输入消息').fill('账号内容')
  await first.getByLabel('发送').click()
  await expect(first.getByText('回复：账号内容')).toBeVisible()

  await second.goto('/')
  await expect(second.getByText('账号内容')).toHaveCount(0)
  await second.getByRole('button', { name: '登录' }).click()
  await second.getByLabel('用户名').fill('alice')
  await second.getByLabel('密码').fill('password-123')
  await second.getByRole('dialog').getByRole('button', { name: '确认' }).click()
  await expect(second.getByText('账号内容').first()).toBeVisible()

  await firstContext.close()
  await secondContext.close()
})

test('switching conversations isolates late stream events', async ({ page }) => {
  const firstThreadId = '00000000-0000-0000-0000-000000000001'
  const secondThreadId = '00000000-0000-0000-0000-000000000002'
  const backend: Backend = {
    next: 2,
    threads: [
      { thread_id: firstThreadId, owner_id: 'temp-1', title: '原对话', title_source: 'manual', created_at: now(), updated_at: now(), turns: [] },
      { thread_id: secondThreadId, owner_id: 'temp-1', title: '目标对话', title_source: 'manual', created_at: now(), updated_at: now(), turns: [{ turn_id: 'target-turn', client_message_id: 'target-client', sequence: 1, user_content: '目标问题', assistant_content: '目标历史\n'.repeat(800), committed_at: now() }] },
    ],
  }
  await mockBackend(page, backend)
  const stream = await installControlledStream(page, backend)
  await page.goto('/')

  await page.getByLabel('输入消息').fill('跨对话流')
  await page.getByLabel('发送').click()
  await stream.waitForRequest()
  stream.emit('started')
  stream.emit('token', { content: '原对话部分' })
  await expect(page.getByText('原对话部分')).toBeVisible()

  await page.getByText('目标对话', { exact: true }).first().click()
  await expect(page.locator('.workspace .title')).toHaveText('目标对话')
  const messages = page.locator('.messages')
  await expect.poll(() => messages.evaluate(element =>
    Math.max(0, element.scrollHeight - element.scrollTop - element.clientHeight),
  )).toBeLessThanOrEqual(64)

  stream.emit('token', { content: '迟到片段' })
  await expect(page.getByText('迟到片段')).toHaveCount(0)
  stream.emit('completed', { answer: '原对话部分迟到片段' })

  // 当前前端在后台 Run 终态时会切回该 Run 所属对话。
  await expect(page.locator('.workspace .title')).toHaveText('原对话')
  await expect(page.getByText('原对话部分迟到片段')).toBeVisible()

  // 再切回目标对话，确认其历史未被迟到流污染。
  await page.getByText('目标对话', { exact: true }).first().click()
  await expect(page.locator('.workspace .title')).toHaveText('目标对话')
  await expect(page.getByText('目标历史'.repeat(1), { exact: false }).first()).toBeVisible()
})

test('long text keeps the composer visible on desktop and 390px mobile', async ({ page }) => {
  const longAnswer = '长文本'.repeat(2500)
  const backend: Backend = { threads: [], next: 0, answers: { '生成长文本': longAnswer } }
  await mockBackend(page, backend)
  await page.goto('/')
  await page.getByLabel('输入消息').fill('生成长文本')
  await page.getByLabel('发送').click()
  await expect(page.getByText(longAnswer)).toBeVisible()

  for (const viewport of [{ width: 1280, height: 720 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport)
    const composer = await page.locator('.composer').evaluate(element => ({
      bottom: element.getBoundingClientRect().bottom,
      viewportHeight: window.innerHeight,
    }))
    expect(composer.viewportHeight).toBe(viewport.height)
    expect(composer.bottom).toBeLessThanOrEqual(composer.viewportHeight + 1)
    const messages = await page.locator('.messages').evaluate(element => ({
      clientHeight: element.clientHeight,
      scrollHeight: element.scrollHeight,
      overflowY: getComputedStyle(element).overflowY,
    }))
    expect(messages.scrollHeight).toBeGreaterThan(messages.clientHeight)
    expect(messages.overflowY).toBe('auto')
  }
})

test('mobile drawer closes with Escape and restores menu focus', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await mockBackend(page, { threads: [], next: 0 })
  await page.goto('/')
  const menu = page.getByLabel('打开会话列表')
  await menu.click()
  await expect(page.locator('#conversation-sidebar')).toHaveClass(/is-open/)
  await page.keyboard.press('Escape')
  await expect(page.locator('#conversation-sidebar')).not.toHaveClass(/is-open/)
  await expect(menu).toBeFocused()
})

const failureOperations: OperationRecord[] = [
  {
    operation_id: 'op-timeout-0001',
    tool_id: 'exec_command',
    tool_call_id: 'call-timeout',
    status: 'failed',
    risk: 'warn',
    error_code: 'command_timeout',
    result_summary: '命令在 30 秒内未完成，已终止',
    source: 'native',
    server_id: null,
    arguments_summary: 'python train.py --epochs 3',
    risk_reason: null,
    timing_ms: 30000,
    artifacts: [],
  },
  {
    operation_id: 'op-reject-0002',
    tool_id: 'exec_command',
    tool_call_id: 'call-reject',
    status: 'rejected',
    risk: 'danger',
    error_code: 'approval_rejected',
    result_summary: '用户在审批中拒绝该命令',
    source: 'native',
    server_id: null,
    arguments_summary: 'rm -rf /tmp/cache',
    risk_reason: '命令包含递归删除操作',
    timing_ms: null,
    artifacts: [],
  },
  {
    operation_id: 'op-unknown-0003',
    tool_id: 'web_fetch',
    tool_call_id: 'call-unknown',
    status: 'error',
    risk: 'info',
    error_code: 'upstream_403_denied',
    result_summary: '上游返回 403，抓取被拒绝',
    source: 'native',
    server_id: null,
    arguments_summary: 'https://example.com',
    risk_reason: null,
    timing_ms: 120,
    artifacts: [],
  },
  {
    operation_id: 'op-ok-0004',
    tool_id: 'read_file',
    tool_call_id: 'call-ok',
    status: 'succeeded',
    risk: 'read',
    error_code: null,
    result_summary: '读取 3 个文件',
    source: 'native',
    server_id: null,
    arguments_summary: 'README.md',
    risk_reason: null,
    timing_ms: 45,
    artifacts: [],
  },
]

test('sse tool events drive incremental updates without per-event refetching', async ({ page }) => {
  const backend: Backend = { threads: [], next: 0 }
  await mockBackend(page, backend)
  const stream = await installControlledStream(page, backend)
  await page.goto('/')

  await page.getByLabel('输入消息').fill('增量工具事件')
  await page.getByLabel('发送').click()
  await stream.waitForRequest()
  stream.emit('started')

  // tool.event 到达即增量渲染 tool_call，不回拉 /api/operations
  stream.emit('runEvent', {
    sequence: 10,
    type: 'tool.event',
    payload: {
      kind: 'started',
      operation_id: 'op-sse-1',
      tool_id: 'exec_command',
      tool_call_id: 'call-sse-1',
      risk: 'safe',
      source: 'native',
      arguments: 'echo hi',
    },
  })
  const call = page.locator('.tool-call', { hasText: 'exec_command' })
  await expect(call).toBeVisible()
  await expect(call.locator('.tool-call-status')).toHaveText('running')

  stream.emit('runEvent', {
    sequence: 11,
    type: 'tool.event',
    payload: {
      kind: 'completed',
      operation_id: 'op-sse-1',
      tool_id: 'exec_command',
      tool_call_id: 'call-sse-1',
      status: 'success',
      summary: '执行完成',
      timing_ms: 12,
      artifacts: [],
    },
  })
  await expect(call.locator('.tool-call-status')).toHaveText('succeeded')

  stream.emit('completed', { answer: '回复：增量工具事件' })
  await expect(page.getByText('回复：增量工具事件')).toBeVisible()

  // 全量校对只发生在建流前/流结束/历史加载，两个端点合计有上限
  // （旧行为每条 run_event 触发 2 次全量 GET，一次多事件 run 会打出 80+ 请求）
  const counts = backend.requestCounts || {}
  expect(counts['operations'] ?? 0).toBeLessThanOrEqual(4)
  expect(counts['event-log'] ?? 0).toBeLessThanOrEqual(4)
})

test('failed operations and run failure get dedicated error presentation', async ({ page }) => {
  const backend: Backend = { threads: [], next: 0, nextRunOperations: failureOperations }
  await mockBackend(page, backend)
  const stream = await installControlledStream(page, backend)
  await page.goto('/')

  await page.getByLabel('输入消息').fill('触发工具失败')
  await page.getByLabel('发送').click()
  await stream.waitForRequest()
  stream.emit('started')
  await expect(page.locator('.think-block')).toBeVisible()
  stream.emit('error', { terminal_message: '模型调用失败（HTTP 402）：账户余额不足' })

  // run 级失败挂在 think 活动块上：标红 + role=alert + terminalMessage 原文
  const failedThink = page.locator('.think-block.is-failed')
  await expect(failedThink).toHaveCount(1)
  await expect(failedThink).toHaveAttribute('role', 'alert')
  await expect(failedThink.locator('.think-summary-inline')).toHaveText('模型调用失败（HTTP 402）：账户余额不足')
  await failedThink.locator('.think-head').click()
  await expect(page.locator('.think-details.think-error')).toHaveText('模型调用失败（HTTP 402）：账户余额不足')

  // 分路径文案出现在失败 tool_call 头部（无独立错误气泡）
  await expect(page.locator('.tool-call-failure-label', { hasText: '命令超时' })).toBeVisible()
  await expect(page.locator('.tool-call-failure-label', { hasText: '审批被拒' })).toBeVisible()
  await expect(page.locator('.tool-call-failure-label', { hasText: '执行失败' })).toBeVisible()
  await expect(page.locator('.bubble.error-bubble')).toHaveCount(0)

  // error_code 徽标原样展示
  await expect(page.locator('.error-code-badge', { hasText: 'command_timeout' }).first()).toBeVisible()
  await expect(page.locator('.error-code-badge', { hasText: 'approval_rejected' }).first()).toBeVisible()
  await expect(page.locator('.error-code-badge', { hasText: 'upstream_403_denied' }).first()).toBeVisible()

  // 已完成的 tool_call 不消失，且不携带失败文案
  const okCall = page.locator('.tool-call', { hasText: 'read_file' })
  await expect(okCall).toBeVisible()
  await expect(okCall.locator('.tool-call-status')).toHaveText('succeeded')
  await expect(okCall.locator('.tool-call-failure-label')).toHaveCount(0)

  // 失败 tool_call 详情可展开（错误码 + 参数），整块可点击
  const timeoutHead = page.locator('.tool-call-head', { hasText: 'command_timeout' }).first()
  await expect(timeoutHead).toHaveCSS('cursor', 'pointer')
  await timeoutHead.click()
  await expect(timeoutHead).toHaveAttribute('aria-expanded', 'true')
  await expect(page.getByText('错误码：command_timeout')).toBeVisible()
  await expect(page.getByText('参数：python train.py --epochs 3')).toBeVisible()
  await timeoutHead.click()
  await expect(timeoutHead).toHaveAttribute('aria-expanded', 'false')

  // 审批被拒 op 展开后可见风险原因
  const rejectHead = page.locator('.tool-call-head', { hasText: 'approval_rejected' }).first()
  await rejectHead.click()
  await expect(page.getByText('风险：命令包含递归删除操作')).toBeVisible()
})

test('run failure surfaces HTTP 403 terminal message in an alert bubble', async ({ page }) => {
  const backend: Backend = { threads: [], next: 0 }
  await mockBackend(page, backend)
  const stream = await installControlledStream(page, backend)
  await page.goto('/')

  await page.getByLabel('输入消息').fill('权限失败')
  await page.getByLabel('发送').click()
  await stream.waitForRequest()
  stream.emit('started')
  stream.emit('error', { terminal_message: '模型调用失败（HTTP 403）：无权访问该模型' })

  const failedThink = page.locator('.think-block.is-failed')
  await expect(failedThink).toHaveAttribute('role', 'alert')
  await expect(failedThink).toContainText('模型调用失败（HTTP 403）：无权访问该模型')
  await expect(page.getByRole('button', { name: '重试' })).toBeVisible()
})

test('awaiting approval operations stay visible and actionable in chat view', async ({ page }) => {
  const pendingOperations: OperationRecord[] = [
    {
      operation_id: 'op-approve-chat-1',
      tool_id: 'exec_command',
      tool_call_id: 'call-appr-chat',
      status: 'awaiting_approval',
      risk: 'danger',
      error_code: null,
      approval_id: 'approval-chat-1',
      result_summary: null,
      source: 'native',
      server_id: null,
      arguments_summary: 'deploy.sh',
      risk_reason: '部署命令需要审批',
      timing_ms: null,
      artifacts: [],
    },
  ]
  const backend: Backend = { threads: [], next: 0, nextRunOperations: pendingOperations }
  await mockBackend(page, backend)
  const stream = await installControlledStream(page, backend)
  await page.goto('/')

  await page.getByLabel('输入消息').fill('聊天内审批')
  await page.getByLabel('发送').click()
  await stream.waitForRequest()
  stream.emit('started')

  // 待审批 tool_call 在聊天流中立即可见，默认展开并带审批按钮
  const head = page.locator('.tool-call-head', { hasText: 'exec_command' })
  await expect(head).toBeVisible()
  await expect(head.locator('.tool-call-status')).toHaveText('awaiting_approval')
  await expect(head).toHaveAttribute('aria-expanded', 'true')
  const approve = page.getByRole('button', { name: '批准', exact: true })
  const reject = page.getByRole('button', { name: '拒绝', exact: true })
  await expect(approve).toBeVisible()
  await expect(reject).toBeVisible()
  await expect(page.getByText('风险：部署命令需要审批')).toBeVisible()

  // 批准后状态即时更新为 succeeded
  await approve.click()
  const headAfter = page.locator('.tool-call', { hasText: 'exec_command' })
  await expect(headAfter.locator('.tool-call-status')).toHaveText('succeeded', { timeout: 10_000 })
})

test('trajectory operations expand and collapse with failure default open', async ({ page }) => {
  const backend: Backend = { threads: [], next: 0, nextRunOperations: failureOperations }
  await mockBackend(page, backend)
  const stream = await installControlledStream(page, backend)
  await page.goto('/')

  await page.getByLabel('输入消息').fill('轨迹失败展示')
  await page.getByLabel('发送').click()
  await stream.waitForRequest()
  stream.emit('started')
  stream.emit('error', { terminal_message: '模型调用失败（HTTP 402）：账户余额不足' })
  await expect(page.getByText('模型调用失败（HTTP 402）：账户余额不足')).toBeVisible()

  await page.getByRole('tab', { name: '轨迹' }).click()

  // 失败 operation 默认展开，详情含错误码、完整摘要与参数
  const timeoutHead = page.locator('.trajectory-operation-head', { hasText: 'command_timeout' })
  await expect(timeoutHead).toHaveAttribute('aria-expanded', 'true')
  const timeoutDetails = page.locator('#operation-details-op-timeout-0001')
  await expect(timeoutDetails).toBeVisible()
  await expect(timeoutDetails).toContainText('错误码：command_timeout')
  await expect(timeoutDetails).toContainText('完整摘要：命令在 30 秒内未完成，已终止')
  await expect(timeoutDetails).toContainText('参数：python train.py --epochs 3')

  // 点击收起再展开
  await timeoutHead.click()
  await expect(timeoutHead).toHaveAttribute('aria-expanded', 'false')
  await expect(timeoutDetails).toHaveCount(0)
  await timeoutHead.click()
  await expect(timeoutHead).toHaveAttribute('aria-expanded', 'true')

  // 成功 operation 默认折叠，可手动展开
  const okHead = page.locator('.trajectory-operation-head', { hasText: 'read_file' })
  await expect(okHead).toHaveAttribute('aria-expanded', 'false')
  await okHead.click()
  await expect(okHead).toHaveAttribute('aria-expanded', 'true')
  await expect(page.getByText('完整摘要：读取 3 个文件')).toBeVisible()

  // 折叠状态下失败摘要仍优先展示
  await expect(page.locator('.trajectory-failure-summary', { hasText: '用户在审批中拒绝该命令' })).toBeVisible()
})

test('approval controls inside trajectory details do not toggle the header', async ({ page }) => {
  const pendingOperations: OperationRecord[] = [
    {
      operation_id: 'op-pending-0001',
      tool_id: 'exec_command',
      tool_call_id: 'call-pending',
      status: 'awaiting_approval',
      risk: 'danger',
      error_code: null,
      approval_id: 'approval-1',
      result_summary: null,
      source: 'native',
      server_id: null,
      arguments_summary: 'deploy.sh',
      risk_reason: '部署命令需要审批',
      timing_ms: null,
      artifacts: [],
    },
  ]
  const backend: Backend = { threads: [], next: 0, nextRunOperations: pendingOperations }
  await mockBackend(page, backend)
  const stream = await installControlledStream(page, backend)
  await page.goto('/')

  await page.getByLabel('输入消息').fill('待审批工具')
  await page.getByLabel('发送').click()
  await stream.waitForRequest()
  stream.emit('started')
  stream.emit('error', { terminal_message: '模型调用失败（HTTP 402）：账户余额不足' })
  await expect(page.getByText('模型调用失败（HTTP 402）：账户余额不足')).toBeVisible()

  await page.getByRole('tab', { name: '轨迹' }).click()
  const head = page.locator('.trajectory-operation-head', { hasText: 'exec_command' })
  await expect(head).toHaveAttribute('aria-expanded', 'false')
  await head.click()
  await expect(head).toHaveAttribute('aria-expanded', 'true')

  // 点击审批区域（非按钮位置）不触发展开头切换
  const approval = page.locator('.trajectory-approval')
  await expect(approval).toBeVisible()
  await approval.click({ position: { x: 10, y: 8 } })
  await expect(head).toHaveAttribute('aria-expanded', 'true')
})
