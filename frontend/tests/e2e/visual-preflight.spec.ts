import { expect, test } from '@playwright/test'

const fingerprint = 'a'.repeat(64)
const shots = [1, 2].map(n => ({ id: `s${n}`, order: n, title: `镜头${n}`, durationSec: 5,
  visualDescription: n === 1 ? '雨夜推门进入便利店' : '店员抬头看向来客',
  action: '走近柜台', emotion: '平静', shotSize: '中景', dialogue: '你终于来了。' }))

function preview(shotId: string) {
  return { ready: true, fingerprint, shotId, model: 'MiniMax-H3', mode: 'ref2va',
    modelConfigRevision: 8, parameters: { resolution: '768P', duration: 5, ratio: '9:16' },
    references: [{ label: '<Picture 1>', role: 'reference_image', name: '小雨', view: 'reference-board', sourceId: 'hash1', fileState: 'exists' }],
    prompt: { kind: 'submission', text: `【镜头】${shotId} 推门进入；【台词】你终于来了。`, platformOptimization: true },
    calls: { text: 0, video: 1 }, price: null, errors: [], warnings: [],
    speech: { dialogue: '你终于来了。', narration: '' },
    style: { name: '日系二维动画', revision: 1 } }
}

test('preflight is read-only, matches submit fingerprint and needs refresh after stale input', async ({ page }, info) => {
  const requests: string[] = [], submissions: Record<string, unknown>[] = []
  let block = false, unavailable = false
  await page.addInitScript(() => localStorage.setItem('comicflow-project-id', 'preflight'))
  await page.route('**/api/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname
    if (request.method() === 'POST') requests.push(path)
    if (path.endsWith('/visual/preflight')) {
      if (unavailable) return route.fulfill({ status: 503, json: { error: 'OFFLINE' } })
      const data = preview(path.includes('/s2/') ? 's2' : 's1')
      return route.fulfill({ json: block ? { ...data, ready: false, errors: ['REFERENCE_FILE_MISSING'] } : data })
    }
    if (path.endsWith('/video-jobs') && request.method() === 'POST') {
      submissions.push(request.postDataJSON())
      return route.fulfill({ status: 409, json: { error: 'PREFLIGHT_STALE' } })
    }
    if (path.endsWith('/video-jobs')) return route.fulfill({ json: { items: [] } })
    if (path === '/api/projects/preflight') return route.fulfill({ json: {
      project: { id: 'preflight', version: 3, stage: 'storyboard-ready', input: { mode: 'import_script' } },
      script: { title: '雨夜', scenes: [], shots }, visualAssets: [], audioAssets: [], jobs: [], timelines: {},
    } })
    return route.fulfill({ json: {} })
  })
  await page.goto('/')
  await page.getByRole('button', { name: '画面', exact: true }).click()
  const panel = page.getByRole('complementary', { name: '生成准备单' })
  await expect(panel.getByText('768P', { exact: true })).toBeVisible()
  await expect(panel.getByText('人物三视图整板', { exact: false })).toBeVisible()
  await expect(page.getByRole('button', { name: '播放镜头' })).toHaveCount(0)
  expect(submissions).toEqual([])
  await panel.getByText('查看提交提示词', { exact: true }).click()
  await expect(panel.locator('pre')).toContainText('s1')
  await page.screenshot({ path: info.outputPath('preflight-desktop.png'), fullPage: true })
  await page.getByRole('button', { name: '生成当前镜头' }).click()
  await expect(page.getByRole('alert')).toContainText('请刷新生成准备单')
  await expect(page.getByRole('button', { name: '生成当前镜头' })).toBeDisabled()
  expect(submissions).toEqual([{ expectedVersion: 3, preflightFingerprint: fingerprint, operationId: expect.any(String) }])
  block = true
  await page.getByRole('button', { name: '刷新准备单' }).click()
  await expect(panel.getByRole('alert')).toContainText('参考图片已不存在')
  await expect(page.getByRole('button', { name: '生成当前镜头' })).toBeDisabled()
  unavailable = true
  await page.getByRole('button', { name: '刷新准备单' }).click()
  await expect(panel.getByRole('alert').filter({ hasText: '准备单读取失败' })).toBeVisible()
  await expect(page.getByRole('button', { name: '生成当前镜头' })).toBeDisabled()
  block = false; unavailable = false
  await page.getByRole('button', { name: /02 镜头2/ }).click()
  await expect(panel.getByText('768P', { exact: true })).toBeVisible()
  await expect(page.getByRole('textbox', { name: '已保存的视觉描述（只读）' })).toHaveValue('店员抬头看向来客')
  await page.setViewportSize({ width: 390, height: 844 })
  await panel.scrollIntoViewIfNeeded()
  await expect(panel).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await panel.screenshot({ path: info.outputPath('preflight-mobile.png') })
  expect(requests.filter(path => !path.endsWith('/preflight'))).toHaveLength(1)
})

test('batch prepares each shot and stops before submitting a missing tail frame', async ({ page }) => {
  const events: string[] = []
  const assets: Record<string, unknown>[] = []
  await page.addInitScript(() => localStorage.setItem('comicflow-project-id', 'batch-preflight'))
  await page.route('**/api/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname
    if (path.endsWith('/preflight')) {
      const id = path.includes('/s2/') ? 's2' : 's1'
      events.push(`prepare-${id}`)
      return route.fulfill({ json: id === 's2' ? { ...preview(id), ready: false, fingerprint: null, errors: ['CASCADE_FRAME_MISSING'] } : preview(id) })
    }
    if (path.endsWith('/video-jobs') && request.method() === 'POST') {
      expect(request.postDataJSON().preflightFingerprint).toBe(fingerprint)
      events.push('submit-s1')
      const asset = { id: 'video', shotId: 's1', valid: true, mediaType: 'video', provider: 'minimax' }
      assets.push(asset)
      return route.fulfill({ status: 202, json: { id: 'job-s1', status: 'succeeded',
        result: { assetId: asset.id, adopted: true, projectVersion: 1 } } })
    }
    if (path.endsWith('/video-jobs')) return route.fulfill({ json: { items: [] } })
    if (path === '/api/projects/batch-preflight') return route.fulfill({ json: {
      project: { id: 'batch-preflight', version: 1, stage: 'storyboard-ready', input: { mode: 'import_script' } },
      script: { title: '雨夜', scenes: [], shots }, visualAssets: assets, audioAssets: [], jobs: [], timelines: {},
    } })
    return route.fulfill({ json: {} })
  })
  await page.goto('/')
  await page.getByRole('button', { name: '画面', exact: true }).click()
  await expect(page.getByText('本地准备检查通过')).toBeVisible()
  await page.getByRole('button', { name: '生成全部 (2)' }).click()
  await expect(page.getByText(/批量生成中断：上一镜头尚无可用尾帧/)).toBeVisible()
  expect(events.filter(e => e.startsWith('submit'))).toEqual(['submit-s1'])
  expect(events.indexOf('prepare-s2')).toBeGreaterThan(events.indexOf('submit-s1'))
})
