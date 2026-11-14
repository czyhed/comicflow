import { test } from '@playwright/test'
import { script } from './fixtures/split-preview-script'

test('debug split preview', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.route('**/api/**', route => route.fulfill({ json: {} }))
  await page.route('**/api/projects', route => route.fulfill({ json: { project: { id: 'prj_v', stage: 'story', version: 1, input: { mode: 'import_story', durationSec: 30 } }, guestSession: { id: 'g', projectId: 'prj_v' } } }))
  await page.route('**/api/projects/prj_v/script/preview', route => route.fulfill({ json: { expectedVersion: 1, script, summary: { scenes: 1, shots: 3, dialogue: 2, narration: 1, issues: [] } } }))
  await page.goto('/')
  await page.getByText('导入内容并整理').click()
  await page.waitForTimeout(500)
  await page.screenshot({ path: 'test-results/debug-before-click.png' })
  await page.getByRole('button', { name: '拆分为剧本' }).click()
  await page.waitForTimeout(2000)
  await page.screenshot({ path: 'test-results/debug-after-click.png' })
})
