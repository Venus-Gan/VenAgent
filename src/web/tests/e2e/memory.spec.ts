import { expect, test, type Page, type Route } from '@playwright/test'

type Identity = {
  actor: { kind: 'guest' | 'user'; owner_id: string; username?: string }
  access_token: string
  access_expires_at: string
  mode: 'durable'
}

type Conversation = {
  conversation_id: string
  owner_id: string
  title: string
  title_source: 'auto' | 'manual'
  created_at: string
  updated_at: string
  messages: Array<Record<string, unknown>>
  runs: Array<Record<string, unknown>>
}

const now = () => new Date().toISOString()

function identity(kind: 'guest' | 'user', ownerId: string): Identity {
  return {
    actor: { kind, owner_id: ownerId, username: kind === 'user' ? 'alice' : undefined },
    access_token: `token-${ownerId}`,
    access_expires_at: new Date(Date.now() + 60_000).toISOString(),
    mode: 'durable',
  }
}

async function installCurrentMemoryBackend(page: Page) {
  let current = identity('guest', 'guest-owner')
  let nextConversation = 0
  let nextMessage = 0
  let nextRun = 0
  let rememberedName = ''
  const conversations: Conversation[] = []

  const visible = () => conversations.filter(item => item.owner_id === current.actor.owner_id)
  const createConversation = (): Conversation => {
    const value: Conversation = {
      conversation_id: `00000000-0000-0000-0000-${String(++nextConversation).padStart(12, '0')}`,
      owner_id: current.actor.owner_id,
      title: '新对话',
      title_source: 'auto',
      created_at: now(),
      updated_at: now(),
      messages: [],
      runs: [],
    }
    conversations.push(value)
    return value
  }

  const memoryMessage = (message: string): string | null => {
    if (message === '记住，我叫小维') {
      rememberedName = '小维'
      return '已保存长期事实，事实已可用，索引正在后台同步。'
    }
    if (message === '我改名叫阿维') {
      rememberedName = '阿维'
      return '记忆已更新，旧事实已 supersede。'
    }
    if (message === '忘记我的名字') {
      rememberedName = ''
      return '匹配记忆已不可召回。'
    }
    if (message === '/memory disable') return '记忆已关闭，现有数据未删除。'
    if (message === '/memory enable') return '记忆已启用。'
    if (message === '/memory delete-all') return '将删除全部活动记忆。确认：/memory delete-all CONFIRM'
    if (message === '/memory delete-all CONFIRM') {
      rememberedName = ''
      return '全部活动记忆已不可召回。'
    }
    return null
  }

  await page.route('**/health', route => route.fulfill({ json: {
    status: 'ok',
    mode: 'durable',
    capabilities: {
      conversation_persistence: 'available',
      restart_recovery: 'available',
    },
  } }))

  await page.route('**/api/**', async (route: Route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    const method = request.method()
    if (path === '/api/auth/refresh' || path === '/api/auth/guest') {
      return route.fulfill({ json: current })
    }
    if (path === '/api/auth/register') {
      current = identity('user', 'user-owner')
      return route.fulfill({ status: 201, json: current })
    }
    if (path === '/api/conversations' && method === 'GET') {
      return route.fulfill({ json: {
        items: visible().map(({ messages, runs, owner_id, ...item }) => item),
        next_cursor: null,
      } })
    }
    if (path === '/api/conversations' && method === 'POST') {
      return route.fulfill({ status: 201, json: createConversation() })
    }
    const conversationId = path.match(/^\/api\/conversations\/([^/]+)$/)?.[1]
    if (conversationId && method === 'GET') {
      const item = visible().find(value => value.conversation_id === conversationId)
      return item
        ? route.fulfill({ json: item })
        : route.fulfill({ status: 404, json: { error: { code: 'not_found', message: '对话不存在' } } })
    }
    const runConversationId = path.match(/^\/api\/conversations\/([^/]+)\/runs$/)?.[1]
    if (runConversationId && method === 'POST') {
      const body = request.postDataJSON()
      if (body.message === '触发非JSON错误') {
        return route.fulfill({ status: 502, contentType: 'text/html', body: '<h1>bad gateway</h1>' })
      }
      const command = memoryMessage(body.message)
      if (command !== null) {
        return route.fulfill({ json: {
          kind: 'memory_command',
          code: 'memory_test_result',
          message: command,
        } })
      }
      const conversation = visible().find(item => item.conversation_id === runConversationId)!
      const inputId = `10000000-0000-0000-0000-${String(++nextMessage).padStart(12, '0')}`
      const outputId = `20000000-0000-0000-0000-${String(++nextMessage).padStart(12, '0')}`
      const runId = `30000000-0000-0000-0000-${String(++nextRun).padStart(12, '0')}`
      conversation.messages.push(
        { message_id: inputId, role: 'user', content: body.message },
        { message_id: outputId, role: 'assistant', content: rememberedName ? `你叫${rememberedName}` : '没有可用姓名记忆' },
      )
      const run = {
        run_id: runId,
        conversation_id: conversation.conversation_id,
        input_message_id: inputId,
        output_message_id: outputId,
        status: 'succeeded',
        phase: 'completed',
        terminal_message: null,
        cancel_requested_at: null,
        retry_eligible: false,
      }
      conversation.runs.push(run)
      return route.fulfill({ status: 202, json: {
        run,
        input_message: conversation.messages.at(-2),
      } })
    }
    const eventRunId = path.match(/^\/api\/runs\/([^/]+)\/events$/)?.[1]
    if (eventRunId) {
      const run = conversations.flatMap(item => item.runs).find(item => item.run_id === eventRunId)
      return route.fulfill({
        contentType: 'text/event-stream',
        body: `event: snapshot\ndata: ${JSON.stringify({ run_id: eventRunId, run })}\n\n`,
      })
    }
    return route.fulfill({ status: 404, json: { error: { code: 'not_found', message: 'not found' } } })
  })
}

async function sendAndExpectNotice(page: Page, message: string, expected: string) {
  await page.getByLabel('输入消息').fill(message)
  await page.getByLabel('发送').click()
  await expect(page.getByRole('status')).toContainText(expected)
}

test('M05 memory survives refresh and exposes stable command and failure states', async ({ page }) => {
  await installCurrentMemoryBackend(page)
  await page.goto('/')

  await page.getByRole('button', { name: '注册' }).click()
  await page.getByRole('dialog', { name: '创建账号' }).getByLabel('用户名').fill('alice')
  await page.getByRole('dialog', { name: '创建账号' }).getByLabel('密码').fill('correct-horse')
  await page.getByRole('dialog', { name: '创建账号' }).getByRole('button', { name: '确认' }).click()
  await expect(page.getByText('账号历史', { exact: true })).toBeVisible()

  await sendAndExpectNotice(page, '记住，我叫小维', '已保存长期事实')
  await page.reload()
  await expect(page.getByText('服务端历史已启用')).toBeVisible()

  await page.getByRole('button', { name: '＋ 新对话' }).click()
  await page.getByLabel('输入消息').fill('我叫什么？')
  await page.getByLabel('发送').click()
  await expect(page.getByText('你叫小维')).toBeVisible()

  await sendAndExpectNotice(page, '我改名叫阿维', '旧事实已 supersede')
  await sendAndExpectNotice(page, '忘记我的名字', '已不可召回')
  await sendAndExpectNotice(page, '/memory disable', '记忆已关闭')
  await sendAndExpectNotice(page, '/memory enable', '记忆已启用')
  await sendAndExpectNotice(page, '/memory delete-all', '确认：/memory delete-all CONFIRM')
  await sendAndExpectNotice(page, '/memory delete-all CONFIRM', '全部活动记忆已不可召回')
  await sendAndExpectNotice(page, '触发非JSON错误', '服务暂时不可用，请稍后重试')
})
