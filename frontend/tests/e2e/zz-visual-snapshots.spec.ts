import { test } from '@playwright/test'

// Temporary visual check for the create-page preview/draft; screenshots only.
const shot = (id: string, order: number, extra: Record<string, unknown> = {}) => ({
  id, sceneId: 'sc1', order, title: `镜头${order}`, action: '推门进入便利店', emotion: '紧张，呼吸急促', shotSize: order % 2 ? '中景' : '近景', durationSec: 5,
  visualDescription: '深夜便利店门口，霓虹灯闪烁，雨水沿玻璃门流下。', dialogue: '林夏：有人吗？', narration: '', cameraMovement: '缓慢推近', ...extra,
})
const script = {
  title: '深夜便利店诡事',
  scenes: [{ id: 'sc1', title: '便利店门口', time: '深夜', location: '街角便利店', narrativeGoal: '建立悬疑', conflict: '无人应答', turningPoint: '', shotIds: ['a', 'b', 'c'] }],
  shots: [shot('a', 1), shot('b', 2, { narration: '那天夜里，雨下得格外大，整条街只剩这家便利店还亮着灯，她不知道里面在等她的是什么。' }), shot('c', 3, { dialogue: '' })],
}

test('create page split preview and draft visual', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  // Mock all API routes - specific routes registered later take precedence
  await page.route('**/api/**', route => route.fulfill({ json: {} }))
  // GET /api/projects/prj_v - snapshot query after creation
  await page.route('**/api/projects/prj_v', route => {
    if (route.request().method() === 'GET') {
      return route.fulfill({ json: {
        project: { id: 'prj_v', stage: 'story', version: 1, input: { mode: 'import_story', durationSec: 30 } },
        jobs: [], visualAssets: [], audioAssets: [], lipSyncAssets: [], creditLedger: [], timelines: {}
      } })
    }
    return route.fulfill({ json: {} })
  })
  // POST /api/projects/prj_v/script/preview
  await page.route('**/api/projects/*/script/preview', route => {
    return route.fulfill({ json: { expectedVersion: 1, script, summary: { scenes: 1, shots: 3, dialogue: 2, narration: 1, issues: [] } } })
  })
  // POST /api/projects - create project
  await page.route('**/api/projects', route => {
    if (route.request().method() === 'POST') {
      return route.fulfill({ json: { project: { id: 'prj_v', stage: 'story', version: 1, input: { mode: 'import_story', durationSec: 30 } }, guestSession: { id: 'g', projectId: 'prj_v' } } })
    }
    return route.fulfill({ json: {} })
  })
  await page.goto('/')
  await page.getByText('导入内容并整理').click()
  await page.locator('textarea').fill('暴雨夜的末班车上，失踪十年的姐姐突然在最后一排回头。')
  await page.getByRole('button', { name: '拆分为剧本' }).click()
  await page.getByRole('region', { name: '剧本拆分预览' }).waitFor({ timeout: 5000 })
  await page.getByRole('region', { name: '剧本拆分预览' }).screenshot({ path: 'test-results/visual/create-split-preview.png' })
})

test('create page generated draft visual', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.addInitScript(() => localStorage.setItem('comicflow-project-id', 'prj_d'))
  await page.route('**/api/**', route => route.fulfill({ json: {} }))
  await page.route('**/api/projects/prj_d', route => route.fulfill({ json: {
    project: { id: 'prj_d', stage: 'script-completed', version: 2, input: { mode: 'automatic', durationSec: 30 } },
    script, jobs: [], visualAssets: [], audioAssets: [], lipSyncAssets: [], creditLedger: [],
  } }))
  await page.goto('/')
  await page.locator('.preview-title-display').waitFor()
  await page.screenshot({ path: 'test-results/visual/create-draft.png' })
})
