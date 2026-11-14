import { expect, test, type Page } from '@playwright/test'
import type { VideoJob } from '../../src/types'

const seed: VideoJob = { id: 'vjob-saved', projectId: 'jobs', shotId: 's1', status: 'recoverable',
  taskId: 'supplier-existing-1', createdAt: '2026-09-19T00:00:00Z', updatedAt: '2026-09-19T00:01:00Z',
  model: 'MiniMax-H3', modelConfigRevision: 3, parameters: { resolution: '768P' },
  callsStarted: { text: 0, video: 1 }, attempts: 1, history: [{ status: 'submitting', at: '2026-09-19T00:00:00Z' }],
  canRecover: true, canLinkTask: false, error: 'PROVIDER_TIMEOUT' }

test('continuity choice is shared by preflight and submission and does not generate on change', async ({ page }) => {
  const state = await setup(page)
  const previews: Record<string, unknown>[] = []
  let submitted: Record<string, unknown> | undefined
  await page.route('**/visual/preflight', async route => {
    previews.push(route.request().postDataJSON())
    await route.fulfill({ json: { ready: true, fingerprint: 'b'.repeat(64),
      parameters: {}, references: [], errors: [], warnings: [], calls: { text: 0, video: 1 } } })
  })
  await page.route('**/shots/s1/video-jobs', async route => {
    submitted = route.request().postDataJSON()
    await route.fulfill({ status: 202, json: { ...seed, status: 'queued' } })
  })
  await page.getByLabel('镜头接续').selectOption('previous-tail')
  await expect.poll(() => previews.at(-1)?.continuityMode).toBe('previous-tail')
  expect(state.submissions).toBe(0)
  await page.getByRole('button', { name: '生成当前镜头', exact: true }).click()
  await expect.poll(() => submitted?.continuityMode).toBe('previous-tail')
  expect(submitted?.preflightFingerprint).toBe('b'.repeat(64))
})

async function setup(page: Page, initial: VideoJob[] = [], withCandidate = false, automatic = false) {
  const state = { items: initial, submissions: 0, recoveries: [] as unknown[], adoptions: 0, unavailable: false,
    completeOnSubmit: false, withCurrent: false, sessionStatus: 'paused', resumes: 0, advances: 0 }
  await page.addInitScript(() => localStorage.setItem('comicflow-project-id', 'jobs'))
  await page.route('**/api/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname
    if (path.endsWith('/visual/preflight')) return route.fulfill({ json: { ready: true, fingerprint: 'a'.repeat(64),
      model: 'MiniMax-H3', parameters: { resolution: '768P' }, references: [], prompt: null,
      calls: { text: 0, video: 1 }, errors: [], warnings: [] } })
    if (path.endsWith('/shots/s1/video-jobs') || path.endsWith('/shots/s2/video-jobs')) {
      state.submissions++
      const job: VideoJob = { ...seed, shotId: path.includes('/s2/') ? 's2' : 's1', status: state.completeOnSubmit ? 'succeeded' : 'queued', taskId: null,
        error: null, canRecover: true, callsStarted: { text: 0, video: 0 } }
      if (state.completeOnSubmit) job.result = { assetId: 'candidate-1', adopted: false, projectVersion: 3 }
      state.items = [job]
      return route.fulfill({ status: 202, json: job })
    }
    if (path.endsWith('/recover')) {
      state.recoveries.push(request.postDataJSON())
      state.items = [{ ...state.items[0], status: 'polling', canRecover: false, error: null }]
      return route.fulfill({ status: 202, json: state.items[0] })
    }
    if (path.endsWith('/adopt')) {
      state.adoptions++
      state.items = [{ ...state.items[0], result: { assetId: 'candidate-1', adopted: true, projectVersion: 3 } }]
      return route.fulfill({ status: 200, json: state.items[0] })
    }
    if (path.endsWith('/video-jobs')) return state.unavailable
      ? route.fulfill({ status: 503, json: { error: 'VIDEO_JOB_STORAGE_UNAVAILABLE' } })
      : route.fulfill({ json: { items: state.items } })
    if (path.endsWith('/video-jobs/vjob-saved')) return route.fulfill({ json: state.items[0] })
    if (path.includes('/generation-session')) {
      if (path.endsWith('/resume')) { state.resumes++; state.sessionStatus = 'ready' }
      if (path.endsWith('/advance')) state.advances++
      return route.fulfill({ json: { id: 'session-1', projectId: 'jobs', mode: 'automatic', stage: 'storyboard-ready',
        status: state.sessionStatus, retryCount: 0, pauseReason: state.sessionStatus === 'paused' ? 'video-awaiting-adoption' : undefined,
        waitingJobId: 'vjob-saved', waitingShotId: 's1' } })
    }
    if (path === '/api/projects/jobs') return route.fulfill({ json: {
      project: { id: 'jobs', version: 3, stage: 'storyboard-ready', input: { mode: automatic ? 'automatic' : 'import_script' } },
      script: { title: '雨夜', scenes: [], shots: [1, 2].map(n => ({ id: `s${n}`, title: `镜头${n}`, order: n,
        durationSec: 5, action: '推门', visualDescription: '雨夜走进便利店', emotion: '平静', shotSize: '中景' })) },
      visualAssets: [
        ...(state.withCurrent ? [{ id: 'old-current', shotId: 's1', mediaType: 'video', valid: true }] : []),
        ...(withCandidate ? [{ id: 'candidate-1', shotId: 's1', mediaType: 'video',
          status: state.items[0]?.result?.adopted ? 'current' : 'candidate', valid: Boolean(state.items[0]?.result?.adopted),
          downloadUrl: 'https://offline.invalid/candidate.mp4' }] : []),
      ],
      audioAssets: [], jobs: [], timelines: {},
    } })
    return route.fulfill({ json: {} })
  })
  await page.goto('/')
  await page.getByRole('button', { name: '画面', exact: true }).click()
  return state
}

test('saved supplier task survives reload and resumes only on explicit action', async ({ page }, info) => {
  const state = await setup(page, [{ ...seed }])
  const panel = page.getByRole('region', { name: '视频任务详情' })
  await panel.getByText('技术详情', { exact: true }).click()
  await expect(panel.getByText('supplier-existing-1', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '生成当前镜头' })).toBeDisabled()
  expect(state.submissions).toBe(0)
  await page.reload()
  await page.getByRole('button', { name: '画面', exact: true }).click()
  await panel.getByText('技术详情', { exact: true }).click()
  await expect(panel.getByText('supplier-existing-1', { exact: true })).toBeVisible()
  expect(state.recoveries).toEqual([])
  await panel.scrollIntoViewIfNeeded()
  await page.screenshot({ path: info.outputPath('video-job-desktop.png'), fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  await panel.scrollIntoViewIfNeeded()
  await expect(panel).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await panel.screenshot({ path: info.outputPath('video-job-mobile.png') })
  await panel.getByRole('button', { name: '继续查询 / 保存已有任务' }).click()
  await expect(panel.getByRole('status')).toHaveText('查询已有供应商任务')
  expect(state.recoveries).toEqual([{ taskId: null }])
  expect(state.submissions).toBe(0)
})

test('batch stops normally at a candidate and reuses it on another click', async ({ page }) => {
  const state = await setup(page, [], true)
  state.completeOnSubmit = true
  await page.getByRole('button', { name: '生成全部 (2)' }).click()
  await expect(page.getByRole('status').filter({ hasText: '等待采用' })).toBeVisible()
  await expect(page.getByText('批量生成中断：', { exact: false })).toHaveCount(0)
  expect(state.submissions).toBe(1)
  await page.getByRole('button', { name: '生成全部 (2)' }).click()
  await expect(page.getByRole('status').filter({ hasText: '等待采用' })).toBeVisible()
  expect(state.submissions).toBe(1)
  await page.reload()
  await page.getByRole('button', { name: '画面', exact: true }).click()
  await expect(page.getByRole('button', { name: '采用此候选视频' })).toBeVisible()
  expect(state.submissions).toBe(1)
})

test('automatic session waits for adoption then requires explicit resume and advance', async ({ page }) => {
  const state = await setup(page, [{ ...seed, status: 'succeeded', canRecover: false,
    result: { assetId: 'candidate-1', adopted: false, projectVersion: 3 } }], true, true)
  const controls = page.getByLabel('生成会话控制')
  await expect(controls.getByRole('button', { name: '继续', exact: true })).toBeDisabled()
  await expect(controls.getByRole('button', { name: '推进', exact: true })).toBeDisabled()
  await page.getByRole('button', { name: '剧本', exact: true }).click()
  await controls.getByRole('button', { name: '查看待采用镜头' }).click()
  await page.getByRole('button', { name: '采用此候选视频' }).click()
  await expect(controls.getByRole('button', { name: '继续', exact: true })).toBeEnabled()
  expect(state.resumes).toBe(0)
  expect(state.advances).toBe(0)
  expect(state.submissions).toBe(0)
  await controls.getByRole('button', { name: '继续', exact: true }).click()
  await expect(controls.getByRole('button', { name: '推进', exact: true })).toBeEnabled()
  expect(state.resumes).toBe(1)
  expect(state.advances).toBe(0)
  await controls.getByRole('button', { name: '推进', exact: true }).click()
  await expect.poll(() => state.advances).toBe(1)
  expect(state.submissions).toBe(0)
})

test('batch cannot skip a replacement candidate when the previous video is still valid', async ({ page }) => {
  const state = await setup(page, [{ ...seed, status: 'succeeded', canRecover: false,
    result: { assetId: 'candidate-1', adopted: false, projectVersion: 3 } }], true)
  state.withCurrent = true
  await page.reload()
  await page.getByRole('button', { name: '画面', exact: true }).click()
  await page.getByRole('button', { name: '生成全部 (1)' }).click()
  await expect(page.getByRole('status').filter({ hasText: '等待采用' })).toBeVisible()
  expect(state.submissions).toBe(0)
})

test('uncertain submission blocks regeneration and links only the supplied task', async ({ page }) => {
  const state = await setup(page, [{ ...seed, status: 'unknown', taskId: null, canRecover: false, canLinkTask: true }])
  await expect(page.getByRole('button', { name: '生成当前镜头' })).toBeDisabled()
  await expect(page.getByRole('button', { name: '生成全部 (2)' })).toBeDisabled()
  const link = page.getByRole('button', { name: '关联并查询已有任务' })
  await expect(link).toBeDisabled()
  await page.getByLabel('已有供应商任务号').fill('known-2')
  await link.click()
  await expect(page.getByRole('region', { name: '视频任务详情' }).getByRole('status')).toHaveText('查询已有供应商任务')
  expect(state.submissions).toBe(0)
  expect(state.recoveries).toEqual([{ taskId: 'known-2' }])
})

test('one click queues once; failed task-list read cannot bypass protection', async ({ page }) => {
  const state = await setup(page)
  await page.getByRole('button', { name: '生成当前镜头' }).click()
  await expect(page.getByRole('region', { name: '视频任务详情' }).getByRole('status')).toHaveText('已排队，等待执行器')
  await expect(page.getByRole('button', { name: '生成当前镜头' })).toBeDisabled()
  await page.getByRole('button', { name: /02 镜头2/ }).click()
  state.unavailable = true
  await page.getByRole('button', { name: '刷新任务记录' }).click()
  await expect(page.getByText(/为避免重复提交，暂时不能生成/)).toBeVisible()
  await expect(page.getByRole('button', { name: '生成当前镜头' })).toBeDisabled()
  expect(state.submissions).toBe(1)
})

test('candidate video can be previewed and explicitly adopted', async ({ page }) => {
  const state = await setup(page, [{ ...seed, status: 'succeeded', canRecover: false,
    result: { assetId: 'candidate-1', adopted: false, projectVersion: 3 } }], true)
  await expect(page.getByText('候选视频 · 尚未用于当前镜头')).toBeVisible()
  await expect(page.locator('video')).toHaveAttribute('src', 'https://offline.invalid/candidate.mp4')
  const panel = page.getByRole('region', { name: '视频任务详情' })
  await panel.getByRole('button', { name: '采用此候选视频' }).click()
  await expect(panel.getByText('此结果已采用。', { exact: true })).toBeVisible()
  expect(state.adoptions).toBe(1)
})

test('leaving a batch stops future submissions without cancelling the supplier job', async ({ page }) => {
  const state = await setup(page)
  await page.getByRole('button', { name: '生成全部 (2)' }).click()
  await expect(page.getByRole('region', { name: '视频任务详情' }).getByRole('status')).toHaveText('已排队，等待执行器')
  await page.getByRole('button', { name: '剧本', exact: true }).click()
  state.items[0] = { ...state.items[0], status: 'succeeded',
    result: { assetId: 'video-1', adopted: true, projectVersion: 3 } }
  await page.getByRole('button', { name: '画面', exact: true }).click()
  await expect(page.getByRole('region', { name: '视频任务详情' }).getByRole('status')).toHaveText('已完成')
  expect(state.submissions).toBe(1)
  expect(state.recoveries).toEqual([])
})
