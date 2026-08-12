import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './tests/e2e',
  use: { baseURL: 'http://127.0.0.1:4173', channel: 'chrome', headless: true, screenshot: 'only-on-failure' },
})
