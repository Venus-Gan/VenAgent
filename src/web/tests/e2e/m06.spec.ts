import { expect, test, type Page } from '@playwright/test'

const identity = {
  actor: { kind: 'guest', owner_id: 'guest-1', username: null },
  access_token: 'm06-token',
  access_expires_at: new Date(Date.now() + 900_000).toISOString(),
  mode: 'temporary',
}

async function mockM06Backend(page: Page) {
  await page.route('**/api/auth/refresh', route =>
    route.fulfill({ status: 401, json: {} }),
  )
  await page.route('**/api/auth/guest', route =>
    route.fulfill({ json: identity }),
  )
  await page.route('**/api/mcp/servers', route =>
    route.fulfill({
      json: [
        {
          server_id: 'fastctx',
          name: 'FastCtx',
          transport: 'stdio',
          enabled: true,
          command: 'node',
          args: [],
          url: null,
          credential_ref: null,
          allow: ['read', 'grep'],
          deny: [],
          declared_tools: [],
        },
      ],
    }),
  )
  await page.route('**/api/tools/catalog', route =>
    route.fulfill({
      json: {
        snapshot_id: 'snapshot-1',
        sandbox_state: 'unavailable',
        policy_version: 'test',
        tools: [
          {
            tool_id: 'exec_command',
            public_name: 'exec_command',
            source: 'native',
            risk: 'warn',
            exposed: false,
            unavailable_reason: 'sandbox_unavailable',
          },
        ],
      },
    }),
  )
  await page.route('**/api/skills', route =>
    route.fulfill({
      json: [
        {
          skill_id: 'research',
          name: 'Research',
          version: '1.0.0',
          description: 'Research skill',
          enabled: true,
        },
      ],
    }),
  )
}

test('M06 control panel renders MCP, tool and skill state', async ({ page }) => {
  await mockM06Backend(page)
  await page.goto('/control')

  await expect(page.getByText('M06 控制面')).toBeVisible()
  await expect(page.getByText('FastCtx', { exact: true })).toBeVisible()
  await expect(page.getByText('exec_command', { exact: true })).toBeVisible()
  await expect(page.getByText('Research', { exact: true })).toBeVisible()
  await expect(page.getByText('sandbox_unavailable', { exact: true })).toBeVisible()
})
