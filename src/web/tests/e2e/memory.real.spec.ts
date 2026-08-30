import { expect, test, type Page } from '@playwright/test'

const baseURL = process.env.VENAGENT_REAL_BASE_URL || ''
const modelTimeout = Number(process.env.VENAGENT_REAL_MODEL_TIMEOUT_MS || 300_000)

test.setTimeout(900_000)

async function sendMemoryCommand(
  page: Page,
  message: string,
  expected?: string,
): Promise<string> {
  await page.getByLabel('输入消息').fill(message)
  await page.getByLabel('发送').click()
  const result = page.locator('[data-testid="command-result"]')
  if (expected) {
    await expect(result).toContainText(expected, { timeout: 30_000 })
  } else {
    await expect(result).toBeVisible({ timeout: 30_000 })
  }
  return (await result.textContent()) || ''
}

async function sendAgentMessage(page: Page, message: string): Promise<string> {
  const before = await page.locator('article.assistant').count()
  await page.getByLabel('输入消息').fill(message)
  await page.getByLabel('发送').click()
  await expect(page.getByLabel('停止生成')).toBeVisible({ timeout: 15_000 }).catch(() => {})
  await expect(page.getByLabel('发送')).toBeVisible({ timeout: modelTimeout })
  await expect
    .poll(() => page.locator('article.assistant').count(), { timeout: modelTimeout })
    .toBeGreaterThan(before)
  const assistant = page.locator('article.assistant').nth(before)
  await expect(assistant.locator('.state')).toHaveCount(0, { timeout: 10_000 })
  return (await assistant.textContent()) || ''
}

async function cleanupAccount(page: Page): Promise<void> {
  try {
    await page.getByRole('button', { name: '注销账号' }).click()
    const dialog = page.getByRole('dialog', { name: '注销账号' })
    await dialog.getByLabel('当前密码').fill('m05-real-acceptance')
    await dialog.getByRole('button', { name: '确认永久注销' }).click()
    await page.getByText('账号历史', { exact: true }).waitFor({ state: 'detached', timeout: 30_000 })
  } catch {
    // 清理失败作为诊断输出，不覆盖原始失败。
    console.error('memory.real cleanup failed')
  }
}

test('real durable M05 memory survives refresh and governs its lifecycle', async ({ page, request }) => {
  test.skip(!baseURL, 'VENAGENT_REAL_BASE_URL is not set')
  const healthResponse = await request.get(`${baseURL}/health`)
  expect(healthResponse.ok()).toBeTruthy()
  const health = await healthResponse.json()
  expect(health.mode).toBe('durable')
  expect(health.capabilities?.long_term_memory).toBe('available')

  const username = `m05_${Date.now().toString(36)}`
  try {
    await page.goto(baseURL)

    await page.getByRole('button', { name: '注册' }).click()
    const dialog = page.getByRole('dialog', { name: '创建账号' })
    await dialog.getByLabel('用户名').fill(username)
    await dialog.getByLabel('密码').fill('m05-real-acceptance')
    await dialog.getByRole('button', { name: '确认' }).click()
    await expect(page.getByText('账号历史', { exact: true })).toBeVisible()

    // 自然语言记忆保存：现在走普通 Agent Run，不再解析模型回答中的 ID。
    await sendAgentMessage(page, '记住，我叫小维')
    const listAfterSave = await sendMemoryCommand(page, '/memory list')
    expect(listAfterSave).toContain('我叫小维')
    const ids = listAfterSave.match(
      /\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b/gi,
    )
    expect(ids).toHaveLength(1)
    const originalId = ids![0]

    await page.reload()
    await expect(page.getByText('服务端历史已启用')).toBeVisible()
    await page.getByRole('button', { name: '＋ 新对话' }).click()
    await expect(page.locator('article.assistant')).toHaveCount(0, { timeout: 30_000 })
    await sendAgentMessage(page, '我叫什么？只回答名字。')
    await expect(page.locator('article.assistant .bubble').last()).toContainText('小维')

    await sendMemoryCommand(page, `/memory show ${originalId}`, '事实：我叫小维')
    const updated = await sendMemoryCommand(
      page,
      `/memory update ${originalId} 我叫阿维`,
      '记忆已更新',
    )
    const updatedId = updated.match(/新 ID：([^；。\s]+)/)?.[1]
    expect(updatedId).toBeTruthy()

    await page.getByRole('button', { name: '＋ 新对话' }).click()
    await expect(page.locator('article.assistant')).toHaveCount(0, { timeout: 30_000 })
    await sendAgentMessage(page, '我叫什么？只回答名字。')
    await expect(page.locator('article.assistant .bubble').last()).toContainText('阿维')

    await sendMemoryCommand(page, `/memory forget ${updatedId}`, '该记忆已不可召回')
    await sendMemoryCommand(page, '/memory list', '没有活动长期记忆')
    await sendMemoryCommand(page, '/memory disable', '记忆已关闭')
    await sendMemoryCommand(page, '/memory enable', '记忆已启用')

    await sendAgentMessage(page, '记住，我住在杭州')
    await sendMemoryCommand(page, '/memory list', '我住在杭州')
    const confirmation = await sendMemoryCommand(page, '/memory delete-all', '5 分钟内确认')
    const token = confirmation.match(/\/memory delete-all ([^\s]+)/)?.[1]
    expect(token).toBeTruthy()
    await sendMemoryCommand(page, `/memory delete-all ${token}`, '全部活动记忆已不可召回')
    await sendMemoryCommand(page, '/memory list', '没有活动长期记忆')
  } finally {
    await cleanupAccount(page)
  }
})
