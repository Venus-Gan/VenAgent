import { expect, test, type Page } from '@playwright/test'

const baseURL = process.env.VENAGENT_REAL_BASE_URL || 'http://127.0.0.1:8090'

test.setTimeout(180_000)

async function sendCommand(page: Page, message: string, expected: string) {
  await page.getByLabel('输入消息').fill(message)
  await page.getByLabel('发送').click()
  await expect(page.getByRole('status')).toContainText(expected, { timeout: 30_000 })
  return (await page.getByRole('status').textContent()) || ''
}

async function sendModelMessage(page: Page, message: string) {
  await page.getByLabel('输入消息').fill(message)
  await page.getByLabel('发送').click()
  await expect(page.getByLabel('停止生成')).toBeVisible({ timeout: 10_000 })
  await expect(page.getByLabel('发送')).toBeVisible({ timeout: 120_000 })
}

test('real durable M05 memory survives refresh and governs its lifecycle', async ({ page }) => {
  const username = `m05_${Date.now().toString(36)}`
  await page.goto(baseURL)

  await page.getByRole('button', { name: '注册' }).click()
  const dialog = page.getByRole('dialog', { name: '创建账号' })
  await dialog.getByLabel('用户名').fill(username)
  await dialog.getByLabel('密码').fill('m05-real-acceptance')
  await dialog.getByRole('button', { name: '确认' }).click()
  await expect(page.getByText('账号历史', { exact: true })).toBeVisible()

  const remembered = await sendCommand(page, '记住，我叫小维', '已保存长期事实')
  const originalId = remembered.match(/ID：([^；。\s]+)/)?.[1]
  expect(originalId).toBeTruthy()

  await page.reload()
  await expect(page.getByText('服务端历史已启用')).toBeVisible()
  await page.getByRole('button', { name: '＋ 新对话' }).click()

  await sendModelMessage(page, '我叫什么？只回答名字。')
  await expect(page.locator('article.assistant .bubble').last()).toContainText('小维')

  await sendCommand(page, `/memory show ${originalId}`, '事实：我叫小维')
  const updated = await sendCommand(
    page,
    `/memory update ${originalId} 我叫阿维`,
    '记忆已更新',
  )
  const updatedId = updated.match(/新 ID：([^；。\s]+)/)?.[1]
  expect(updatedId).toBeTruthy()

  await page.getByRole('button', { name: '＋ 新对话' }).click()
  await sendModelMessage(page, '我叫什么？只回答名字。')
  await expect(page.locator('article.assistant .bubble').last()).toContainText('阿维')

  await sendCommand(page, `/memory forget ${updatedId}`, '该记忆已不可召回')
  await sendCommand(page, '/memory list', '没有活动长期记忆')
  await sendCommand(page, '/memory disable', '记忆已关闭')
  await sendCommand(page, '/memory enable', '记忆已启用')

  await sendCommand(page, '记住，我住在杭州', '已保存长期事实')
  const confirmation = await sendCommand(page, '/memory delete-all', '5 分钟内确认')
  const token = confirmation.match(/\/memory delete-all ([^\s]+)/)?.[1]
  expect(token).toBeTruthy()
  await sendCommand(page, `/memory delete-all ${token}`, '全部活动记忆已不可召回')
  await sendCommand(page, '/memory list', '没有活动长期记忆')
})
