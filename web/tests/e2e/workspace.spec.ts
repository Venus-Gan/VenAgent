import { expect, test, type Page } from '@playwright/test'

type Turn = { turn_id: string; client_message_id: string; sequence: number; user_content: string; assistant_content: string; committed_at: string }
type Thread = { thread_id: string; owner_id: string; title: string; title_source: 'auto' | 'manual'; created_at: string; updated_at: string; turns: Turn[] }
type StreamOutcome = 'completed' | 'error' | 'cancelled' | 'disconnect' | 'eof'
type ActorIdentity = ReturnType<typeof identity>
type IdentityState = { actor: ActorIdentity }
type Backend = { threads: Thread[]; next: number; outcomes?: Record<string, StreamOutcome[]>; answers?: Record<string, string>; delays?: Record<string, number> }
type ControlledStream = {
  waitForRequest: () => Promise<{ thread_id: string; message: string; client_message_id: string }>
  emit: (event: 'started' | 'token' | 'completed', payload?: Record<string, unknown>) => void
}

const now = () => new Date().toISOString()
const identity = (kind: 'guest' | 'user' | 'temporary_guest', owner: string, username?: string) => ({
  actor: { kind, owner_id: owner, username: username || null },
  access_token: `${kind}-access-token`,
  access_expires_at: new Date(Date.now() + 900_000).toISOString(),
  mode: kind === 'temporary_guest' ? 'temporary' : 'durable',
})

async function installControlledStream(page: Page, backend: Backend): Promise<ControlledStream> {
  type StreamRequest = { thread_id: string; message: string; client_message_id: string }
  let request: StreamRequest | undefined
  let resolveRequest: ((value: StreamRequest) => void) | undefined
  let resolveChunk: ((value: string | null) => void) | undefined
  const queuedChunks: Array<string | null> = []
  const requestPromise = new Promise<StreamRequest>(resolve => { resolveRequest = resolve })

  await page.exposeFunction('__venagentControlledStreamRequest', (value: StreamRequest) => {
    request = value
    resolveRequest?.(value)
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
      if (url.pathname !== '/api/chat/stream') return originalFetch(input, init)
      const body = JSON.parse(String(init?.body || '{}'))
      const controls = window as typeof window & {
        __venagentControlledStreamRequest: (value: unknown) => Promise<void>
        __venagentControlledStreamNext: () => Promise<string | null>
      }
      await controls.__venagentControlledStreamRequest(body)
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
    waitForRequest: () => requestPromise,
    emit(event, payload = {}) {
      if (!request) throw new Error('controlled stream request has not started')
      const runId = '20000000-0000-0000-0000-000000000001'
      const sequence = event === 'started' ? 1 : event === 'token' ? 2 : 3
      const data = { version: 1, sequence, thread_id: request.thread_id, run_id: runId, ...payload }
      if (event === 'completed') {
        const thread = backend.threads.find(item => item.thread_id === request?.thread_id)
        if (thread && !thread.turns.some(turn => turn.client_message_id === request?.client_message_id)) {
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
      }
      const chunk = `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`
      if (resolveChunk) {
        const resolve = resolveChunk
        resolveChunk = undefined
        resolve(chunk)
      } else {
        queuedChunks.push(chunk)
      }
      if (event === 'completed') queuedChunks.push(null)
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
    if (path === '/api/threads' && method === 'GET') return route.fulfill({ json: {
      items: ownerThreads().map(({ turns, owner_id, ...thread }) => thread), next_cursor: null,
    } })
    if (path === '/api/threads' && method === 'POST') {
      const id = `00000000-0000-0000-0000-${String(++backend.next).padStart(12, '0')}`
      const thread: Thread = { thread_id: id, owner_id: currentActor().actor.owner_id, title: '新对话', title_source: 'auto', created_at: now(), updated_at: now(), turns: [] }
      backend.threads.push(thread)
      return route.fulfill({ status: 201, json: thread })
    }
    const threadId = path.match(/^\/api\/threads\/([^/]+)$/)?.[1]
    if (threadId) {
      const thread = backend.threads.find(item => item.thread_id === threadId && item.owner_id === currentActor().actor.owner_id)
      if (!thread) return route.fulfill({ status: 404, json: { error: { code: 'thread_not_found', message: '对话不存在' } } })
      if (method === 'GET') return route.fulfill({ json: thread })
      if (method === 'PATCH') {
        const body = request.postDataJSON()
        thread.title = body.title.trim()
        thread.title_source = 'manual'
        thread.updated_at = now()
        return route.fulfill({ json: thread })
      }
      if (method === 'DELETE') {
        backend.threads.splice(backend.threads.indexOf(thread), 1)
        return route.fulfill({ status: 204 })
      }
    }
    if (path === '/api/chat/stream') {
      const body = request.postDataJSON()
      const delay = backend.delays?.[body.message] || 0
      if (delay) await new Promise(resolve => setTimeout(resolve, delay))
      const thread = backend.threads.find(item => item.thread_id === body.thread_id && item.owner_id === currentActor().actor.owner_id)!
      const committed = thread.turns.find(item => item.client_message_id === body.client_message_id)
      const outcome = committed ? 'completed' : backend.outcomes?.[body.message]?.shift() || 'completed'
      if (outcome === 'disconnect') return route.abort('connectionfailed')
      const answer = committed?.assistant_content || backend.answers?.[body.message] || `回复：${body.message}`
      const visibleText = outcome === 'completed' ? answer : `部分回复：${body.message}`
      if (outcome === 'completed' && !committed) {
        thread.turns.push({ turn_id: `turn-${thread.turns.length + 1}`, client_message_id: body.client_message_id, sequence: thread.turns.length + 1, user_content: body.message, assistant_content: answer, committed_at: now() })
        if (thread.title_source === 'auto' && thread.title === '新对话') thread.title = body.message.slice(0, 28)
        thread.updated_at = now()
      }
      const run = '10000000-0000-0000-0000-000000000001'
      if (outcome === 'eof') {
        const partial = `部分回复：${body.message}`
        const eofEvents = [
          `event: started\ndata: ${JSON.stringify({ version: 1, sequence: 1, thread_id: body.thread_id, run_id: run })}\n\n`,
          `event: token\ndata: ${JSON.stringify({ version: 1, sequence: 2, thread_id: body.thread_id, run_id: run, content: partial })}\n\n`,
        ].join('')
        return route.fulfill({ contentType: 'text/event-stream', body: eofEvents })
      }
      const events = [
        `event: started\ndata: ${JSON.stringify({ version: 1, sequence: 1, thread_id: body.thread_id, run_id: run })}\n\n`,
        `event: token\ndata: ${JSON.stringify({ version: 1, sequence: 2, thread_id: body.thread_id, run_id: run, content: visibleText })}\n\n`,
        outcome === 'completed'
          ? `event: completed\ndata: ${JSON.stringify({ version: 1, sequence: 3, thread_id: body.thread_id, run_id: run, answer })}\n\n`
          : outcome === 'cancelled'
            ? `event: cancelled\ndata: ${JSON.stringify({ version: 1, sequence: 3, thread_id: body.thread_id, run_id: run })}\n\n`
            : `event: error\ndata: ${JSON.stringify({ version: 1, sequence: 3, thread_id: body.thread_id, run_id: run, error: { code: 'model_error', message: '生成失败，请重试。' } })}\n\n`,
      ].join('')
      return route.fulfill({ contentType: 'text/event-stream', body: events })
    }
    if (path.includes('/cancel')) return route.fulfill({ status: 202, json: { status: 'cancel_requested' } })
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
  await expect(page.getByText('本机历史')).toHaveCount(0)
  await expect(page.getByText('仅本地')).toHaveCount(0)
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

test('failed partial survives reload and keeps its position before a later committed turn', async ({ page }) => {
  const backend: Backend = { threads: [], next: 0, outcomes: { '失败 A': ['error', 'completed'] } }
  await mockBackend(page, backend, 'durable')
  await page.goto('/')

  await page.getByLabel('输入消息').fill('失败 A')
  await page.getByLabel('发送').click()
  await expect(page.getByText('部分回复：失败 A')).toBeVisible()
  await expect(page.getByText('发送失败').first()).toBeVisible()

  await page.getByLabel('输入消息').fill('成功 B')
  await page.getByLabel('发送').click()
  await expect(page.getByText('回复：成功 B')).toBeVisible()
  await page.reload()

  await expect(page.locator('.messages .bubble')).toHaveText([
    '失败 A',
    '部分回复：失败 A',
    '成功 B',
    '回复：成功 B',
  ])
  expect(backend.threads[0].turns.map(turn => turn.user_content)).toEqual(['成功 B'])

  await page.getByRole('button', { name: '重试' }).click()
  await expect(page.getByText('回复：失败 A', { exact: true })).toBeVisible()
  await page.reload()
  await expect(page.locator('.messages .bubble')).toHaveText([
    '失败 A',
    '回复：失败 A',
    '成功 B',
    '回复：成功 B',
  ])
  expect(backend.threads[0].turns.map(turn => turn.user_content)).toEqual(['成功 B', '失败 A'])
})

test('cancelled partial remains local after reload', async ({ page }) => {
  const backend: Backend = { threads: [], next: 0, outcomes: { '取消消息': ['cancelled'] } }
  await mockBackend(page, backend, 'durable')
  await page.goto('/')

  await page.getByLabel('输入消息').fill('取消消息')
  await page.getByLabel('发送').click()
  await expect(page.getByText('部分回复：取消消息')).toBeVisible()
  await expect(page.getByText('已停止生成')).toBeVisible()
  await page.reload()

  await expect(page.getByText('部分回复：取消消息')).toBeVisible()
  await expect(page.getByText('已停止生成')).toBeVisible()
  expect(backend.threads[0].turns).toHaveLength(0)
})

test('stopping before started keeps the user message sent and marks only the assistant stopped', async ({ page }) => {
  const backend: Backend = { threads: [], next: 0, delays: { '立即停止': 2_000 } }
  await mockBackend(page, backend, 'durable')
  await page.goto('/')

  await page.getByLabel('输入消息').fill('立即停止')
  await page.getByLabel('发送').click()
  await page.getByLabel('停止生成').click()

  await expect(page.getByText('立即停止', { exact: true })).toBeVisible()
  await expect(page.getByText('已停止生成')).toBeVisible()
  await expect(page.getByText('发送中')).toHaveCount(0)
  await expect(page.getByText('连接已中断')).toHaveCount(0)
  expect(backend.threads[0].turns).toHaveLength(0)
})

test('network disconnect remains local and is labelled interrupted', async ({ page }) => {
  const backend: Backend = { threads: [], next: 0, outcomes: { '网络中断': ['disconnect'] } }
  await mockBackend(page, backend, 'durable')
  await page.goto('/')

  await page.getByLabel('输入消息').fill('网络中断')
  await page.getByLabel('发送').click()

  await expect(page.getByText('网络中断', { exact: true })).toBeVisible()
  await expect(page.getByText('连接已中断').first()).toBeVisible()
  await expect(page.getByRole('button', { name: '重试' })).toBeVisible()
  expect(backend.threads[0].turns).toHaveLength(0)
})

test('restored in-flight cache becomes interrupted and remains retryable', async ({ page }) => {
  const threadId = '00000000-0000-0000-0000-000000000001'
  const backend: Backend = { threads: [{
    thread_id: threadId,
    owner_id: 'guest-1',
    title: '中断对话',
    title_source: 'auto',
    created_at: now(),
    updated_at: now(),
    turns: [],
  }], next: 1 }
  await page.addInitScript(({ threadId }) => localStorage.setItem('venagent-conversations-v2', JSON.stringify({
    version: 2,
    activeId: threadId,
    conversations: [{
      threadId,
      ownerId: 'guest-1',
      ownerKind: 'guest',
      source: 'server',
      title: '中断对话',
      titleSource: 'auto',
      updatedAt: Date.now(),
      messages: [
        { id: 'pending-user', clientMessageId: 'pending-client', role: 'user', text: '刷新中断', status: 'sending' },
        { id: 'pending-assistant', role: 'assistant', text: '已有部分', status: 'streaming' },
      ],
    }],
  })), { threadId })
  await mockBackend(page, backend, 'durable')
  const detailLoaded = page.waitForResponse(response => new URL(response.url()).pathname === `/api/threads/${threadId}`)
  await page.goto('/')
  await detailLoaded

  await expect(page.getByText('刷新中断', { exact: true })).toBeVisible()
  await expect(page.getByText('已有部分', { exact: true })).toBeVisible()
  await expect(page.getByText('连接已中断').first()).toBeVisible()
  await expect(page.getByRole('button', { name: '重试' })).toBeVisible()
  await page.getByRole('button', { name: '重试' }).click()
  await expect(page.getByText('回复：刷新中断', { exact: true })).toBeVisible()
  expect(backend.threads[0].turns).toHaveLength(1)
  expect(backend.threads[0].turns[0].client_message_id).toBe('pending-client')
})

test('retry reuses the local attempt and converges to one committed pair', async ({ page }) => {
  const backend: Backend = { threads: [], next: 0, outcomes: { '重试消息': ['error', 'completed'] } }
  await mockBackend(page, backend, 'durable')
  await page.goto('/')

  await page.getByLabel('输入消息').fill('重试消息')
  await page.getByLabel('发送').click()
  await expect(page.getByText('部分回复：重试消息')).toBeVisible()
  await page.getByRole('button', { name: '重试' }).click()
  await expect(page.getByText('回复：重试消息', { exact: true })).toBeVisible()
  await page.reload()

  await expect(page.locator('.messages .bubble')).toHaveText(['重试消息', '回复：重试消息'])
  expect(backend.threads[0].turns).toHaveLength(1)
})

test('thread_not_found removes the browser reference without creating local history', async ({ page }) => {
  const backend: Backend = { threads: [], next: 0 }
  await mockBackend(page, backend, 'durable')
  const created = page.waitForResponse(response =>
    new URL(response.url()).pathname === '/api/threads' && response.request().method() === 'POST',
  )
  await page.goto('/')
  await created
  const missingTitle = backend.threads[0].title
  backend.threads.splice(0)

  await page.getByText(missingTitle, { exact: true }).first().click()

  await expect(page.getByText('对话已不存在，已移除本地引用。')).toBeVisible()
  await expect(page.getByText('本机历史')).toHaveCount(0)
  await expect(page.getByText('仅本地')).toHaveCount(0)
  expect(backend.threads).toHaveLength(1)
})

test('cross-tab logout hides the previous owner content before guest refresh', async ({ browser }) => {
  const backend: Backend = { threads: [], next: 0 }
  const sharedIdentity: IdentityState = { actor: identity('guest', 'guest-1') }
  const context = await browser.newContext()
  const first = await context.newPage()
  const second = await context.newPage()
  await mockBackend(first, backend, 'durable', sharedIdentity)
  await mockBackend(second, backend, 'durable', sharedIdentity)
  await first.goto('/')
  await second.goto('/')

  await first.getByRole('button', { name: '登录' }).click()
  await first.getByLabel('用户名').fill('alice')
  await first.getByLabel('密码').fill('password-123')
  await first.getByRole('dialog').getByRole('button', { name: '确认' }).click()
  await expect(second.getByText('alice')).toBeVisible()

  await first.getByLabel('输入消息').fill('账号私有消息')
  await first.getByLabel('发送').click()
  await expect(first.getByText('回复：账号私有消息')).toBeVisible()
  await second.getByRole('button', { name: '刷新历史' }).click()
  await expect(second.getByText('账号私有消息').first()).toBeVisible()

  await first.getByRole('button', { name: '退出' }).click()

  await expect(second.getByText('alice')).toHaveCount(0)
  await expect(second.getByText('账号私有消息')).toHaveCount(0)
  await expect(second.getByText('匿名使用')).toBeVisible()
  await context.close()
})

test('assistant text renders in multiple visible steps before completion', async ({ page }) => {
  const backend: Backend = { threads: [], next: 0 }
  const stream = await installControlledStream(page, backend)
  await mockBackend(page, backend)
  await page.goto('/')

  await page.getByLabel('输入消息').fill('分段回复')
  await page.getByLabel('发送').click()
  await stream.waitForRequest()
  await expect(page.getByText('发送中')).toBeVisible()

  stream.emit('started')
  await expect(page.getByText('思考中')).toBeVisible()
  await expect(page.getByText('发送中')).toHaveCount(0)

  stream.emit('token', { content: '第一段' })
  const assistant = page.locator('.row.assistant .bubble')
  await expect(assistant).toHaveText('第一段')
  await expect(page.getByText('生成中')).toBeVisible()

  stream.emit('token', { content: '第二段' })
  await expect(assistant).toHaveText('第一段第二段')
  await expect(page.getByText('生成中')).toBeVisible()

  stream.emit('completed', { answer: '第一段第二段' })
  await expect(assistant).toHaveText('第一段第二段')
  await expect(page.getByText('生成中')).toHaveCount(0)
  await expect(page.getByLabel('发送')).toBeVisible()
})

for (const viewport of [{ width: 1280, height: 720 }, { width: 390, height: 844 }]) {
  test(`streaming follows, pauses, and resumes at ${viewport.width}px`, async ({ page }) => {
    await page.setViewportSize(viewport)
    const backend: Backend = { threads: [], next: 0 }
    const stream = await installControlledStream(page, backend)
    await mockBackend(page, backend)
    await page.goto('/')

    await page.getByLabel('输入消息').fill('滚动测试')
    await page.getByLabel('发送').click()
    await stream.waitForRequest()
    stream.emit('started')
    stream.emit('token', { content: '第一段\n'.repeat(500) })

    const messages = page.locator('.messages')
    const assistant = page.locator('.row.assistant .bubble')
    await expect.poll(() => messages.evaluate(element =>
      Math.max(0, element.scrollHeight - element.scrollTop - element.clientHeight),
    )).toBeLessThanOrEqual(64)
    const firstLength = await assistant.evaluate(element => element.textContent?.length || 0)
    expect(firstLength).toBeGreaterThan(0)

    await messages.evaluate(element => {
      element.scrollTop = 0
      element.dispatchEvent(new Event('scroll'))
    })
    const pausedTop = await messages.evaluate(element => element.scrollTop)
    stream.emit('token', { content: '第二段\n'.repeat(500) })
    await expect.poll(() => assistant.evaluate(element => element.textContent?.length || 0)).toBeGreaterThan(firstLength)
    await expect.poll(() => messages.evaluate(element => element.scrollTop)).toBeLessThanOrEqual(pausedTop + 1)

    await messages.evaluate(element => {
      element.scrollTop = element.scrollHeight
      element.dispatchEvent(new Event('scroll'))
    })
    stream.emit('token', { content: '第三段\n'.repeat(200) })
    await expect.poll(() => messages.evaluate(element =>
      Math.max(0, element.scrollHeight - element.scrollTop - element.clientHeight),
    )).toBeLessThanOrEqual(64)

    const composer = await page.locator('.composer').evaluate(element => ({
      bottom: element.getBoundingClientRect().bottom,
      viewportHeight: window.innerHeight,
      windowScrollY: window.scrollY,
    }))
    expect(composer.bottom).toBeLessThanOrEqual(viewport.height + 1)
    expect(composer.viewportHeight).toBe(viewport.height)
    expect(composer.windowScrollY).toBe(0)

    stream.emit('completed', { answer: `${'第一段\n'.repeat(500)}${'第二段\n'.repeat(500)}${'第三段\n'.repeat(200)}` })
    await expect(page.getByText('生成中')).toHaveCount(0)
    await expect(page.getByLabel('发送')).toBeVisible()
  })
}

test('switching conversations isolates late stream events and keeps the new thread at the bottom', async ({ page }) => {
  const firstThreadId = '00000000-0000-0000-0000-000000000001'
  const secondThreadId = '00000000-0000-0000-0000-000000000002'
  const backend: Backend = {
    next: 2,
    threads: [
      {
        thread_id: firstThreadId,
        owner_id: 'temp-1',
        title: '原对话',
        title_source: 'manual',
        created_at: now(),
        updated_at: now(),
        turns: [],
      },
      {
        thread_id: secondThreadId,
        owner_id: 'temp-1',
        title: '目标对话',
        title_source: 'manual',
        created_at: now(),
        updated_at: now(),
        turns: [{
          turn_id: 'target-turn',
          client_message_id: 'target-client',
          sequence: 1,
          user_content: '目标问题',
          assistant_content: '目标历史\n'.repeat(800),
          committed_at: now(),
        }],
      },
    ],
  }
  const stream = await installControlledStream(page, backend)
  await mockBackend(page, backend)
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

  const historyReloaded = page.waitForResponse(response =>
    new URL(response.url()).pathname === '/api/threads' && response.request().method() === 'GET',
  )
  stream.emit('token', { content: '迟到片段' })
  stream.emit('completed', { answer: '原对话部分迟到片段' })
  await historyReloaded

  await expect(page.locator('.workspace .title')).toHaveText('目标对话')
  await expect(page.getByText('原对话部分迟到片段')).toHaveCount(0)
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
