import { expect, test } from '@playwright/test'

const baseURL = process.env.VENAGENT_REAL_BASE_URL || ''
const frontendURL = process.env.VENAGENT_REAL_FRONTEND_URL || 'http://127.0.0.1:5173'
const modelTimeout = Number(process.env.VENAGENT_REAL_MODEL_TIMEOUT_MS || 300_000)

test.setTimeout(modelTimeout * 2)

test('real Vue flow executes one sandboxed native tool', async ({ page, request }) => {
  test.skip(!baseURL, 'VENAGENT_REAL_BASE_URL is not set')

  const healthResponse = await request.get(`${baseURL}/health`)
  expect(healthResponse.ok()).toBeTruthy()
  const health = await healthResponse.json()
  expect(health.mode).toBe('durable')
  expect(health.capabilities?.run_execution).toBe('available')

  await page.goto(`${frontendURL}/control`)
  await expect(page.getByText('M06 控制面')).toBeVisible()
  const execTool = page.locator('.tool-card').filter({ hasText: 'exec_command' })
  await expect(execTool).toContainText('native · warn')
  await expect(execTool).toContainText('exposed')

  await page.getByRole('link', { name: '返回对话' }).click()
  await expect(page.getByLabel('输入消息')).toBeVisible()
  const assistantCount = await page.locator('article.assistant').count()
  const marker = `M06_REAL_TOOL_${Date.now().toString(36)}`
  await page.getByLabel('输入消息').fill(
    `只调用一次 exec_command。请传 command="sh"，args=["-c","printf ${marker}"]，不要把整行拼进 command，也不要调用第二个工具；执行后在最终回答中原样返回命令输出，不要只解释。`,
  )
  await page.getByLabel('发送').click()

  const approve = page.getByRole('button', { name: '批准' }).last()
  const outcome = await Promise.race([
    approve.waitFor({ state: 'visible', timeout: modelTimeout }).then(() => 'approval'),
    (async () => {
      await expect
        .poll(() => page.locator('article.assistant').count(), { timeout: modelTimeout })
        .toBeGreaterThan(assistantCount)
      const directAnswer = page.locator('article.assistant').nth(assistantCount)
      await expect(directAnswer.locator('.state')).toHaveCount(0, { timeout: modelTimeout })
      return 'final'
    })(),
  ])
  if (outcome === 'final') {
    const directText = await page.locator('article.assistant').nth(assistantCount).textContent()
    throw new Error(`model finalized without tool approval: ${directText || ''}`)
  }
  await approve.click()

  await expect
    .poll(() => page.locator('article.assistant').count(), { timeout: modelTimeout })
    .toBeGreaterThan(assistantCount)
  const assistant = page.locator('article.assistant').nth(assistantCount)
  await expect(assistant.locator('.state')).toHaveCount(0, { timeout: modelTimeout })
  await expect(assistant).toContainText(marker, { timeout: modelTimeout })

  const trajectory = assistant.getByRole('button', { name: '执行轨迹' })
  await trajectory.click()
  await expect(assistant).toContainText('Native · exec_command')
  await expect(assistant).toContainText('succeeded')
})
