import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './tests/integration',
  workers: 1,
  timeout: 300_000,
  expect: { timeout: 30_000 },
  use: { baseURL: 'http://127.0.0.1:4184', trace: 'retain-on-failure' },
  outputDir: `${process.env.COMICFLOW_VERIFY_OUTPUT || '../var/verification/full-flow-20260921'}/browser`,
})
