import { expect, test, type Page } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { createServer } from 'node:http'

const entries = [
  { id: 'new', title: '推门', shotId: 's1', status: 'current', createdAt: '2026-09-18T00:00:00Z', model: 'MiniMax-H3', durationMs: 5000 },
  { id: 'old', title: '推门旧版', shotId: 's1', status: 'historical', createdAt: null, model: null, durationMs: null },
  { id: 'lost', title: '离场旧版', shotId: 's2', status: 'stale', createdAt: null, model: null, durationMs: null },
].map(e => ({ ...e, projectId: 'resources', projectTitle: '雨夜', kind: 'shot', sourceAvailable: true, fileState: 'unchecked' }))

async function setup(page: Page, resources = entries, mediaUrl = '/fixture-video.mp4') {
  const writes: string[] = []
  const accesses: string[] = []
  let failList = false
  await page.addInitScript(() => localStorage.setItem('comicflow-project-id', 'resources'))
  await page.route('**/api/**', async route => {
    const request = route.request()
    const url = new URL(request.url())
    if (request.method() !== 'GET') writes.push(url.pathname)
    if (url.pathname.endsWith('/video-resources')) {
      if (failList) return route.fulfill({ status: 503, json: { error: 'STORAGE_UNAVAILABLE' } })
      const filtered = resources.filter(e => (!url.searchParams.get('kind') || url.searchParams.get('kind') === 'all' || e.kind === url.searchParams.get('kind'))
        && (!url.searchParams.get('shot_id') || e.shotId === url.searchParams.get('shot_id'))
        && (!url.searchParams.get('status') || url.searchParams.get('status') === 'all' || e.status === url.searchParams.get('status')))
      const offset = Number(url.searchParams.get('offset') ?? 0)
      return route.fulfill({ json: { items: filtered.slice(offset, offset + 24), total: filtered.length, offset, limit: 24 } })
    }
    if (url.pathname.endsWith('/access')) {
      accesses.push(url.pathname + url.search)
      if (url.pathname.includes('/lost/')) return route.fulfill({ status: 404, json: { error: 'RESOURCE_FILE_MISSING' } })
      return route.fulfill({ json: { url: `${mediaUrl}?revision=${accesses.length}&download=${url.searchParams.get('download')}`, posterUrl: null, filename: 'video.mp4', expiresAt: '2030-01-01T00:00:00Z' } })
    }
    if (url.pathname === '/api/projects/resources') return route.fulfill({ json: {
      project: { id: 'resources', stage: 'storyboard-ready', version: 1, input: { mode: 'import_script' } },
      script: { title: '雨夜', scenes: [{ id: 'scene1', title: '店内', shotIds: ['s1', 's2'] }],
        shots: [{ id: 's1', title: '推门', order: 1 }, { id: 's2', title: '离场', order: 2 }] },
      visualAssets: [{ id: 'new', shotId: 's1', valid: true, mediaType: 'video' }], jobs: [], timelines: {}, audioAssets: [],
    } })
    return route.fulfill({ json: {} })
  })
  await page.route('**/fixture-video.mp4?*', route => route.fulfill({ status: 404, body: '' }))
  await page.goto('/')
  await page.getByRole('button', { name: '资源', exact: true }).click()
  return { writes, accesses, fail: () => { failList = true } }
}

test('browse old versions, renew media, download and locate source without generation', async ({ page }) => {
  const { writes, accesses } = await setup(page)
  await expect(page.getByRole('heading', { name: '视频资源' })).toBeVisible()
  await expect(page.getByText('推门旧版', { exact: true })).toBeVisible()
  await expect(page.getByText('模型未知').first()).toBeVisible()
  expect(accesses).toEqual([])
  await page.getByLabel('视频状态').selectOption('historical')
  await page.getByRole('button', { name: '预览 推门旧版', exact: true }).click()
  await expect(page.getByLabel('历史视频预览')).toHaveAttribute('src', /revision=1/)
  await expect(page.getByRole('button', { name: '重新获取播放链接' })).toBeVisible()
  await page.getByRole('button', { name: '重新获取播放链接' }).click()
  await expect(page.getByLabel('历史视频预览')).toHaveAttribute('src', /revision=2/)
  await page.getByRole('button', { name: '下载 推门旧版', exact: true }).click()
  await expect(page.getByRole('link', { name: '保存视频文件' })).toHaveAttribute('href', /revision=3/)
  expect(accesses[2]).toContain('download=true')
  await page.getByRole('button', { name: '来源镜头 推门旧版', exact: true }).click()
  await expect(page.getByText('动态镜头预览')).toBeVisible()
  expect(writes.filter(path => !path.endsWith('/visual/preflight'))).toEqual([])
})

test('missing files and list errors remain visible; narrow screen works', async ({ page }, info) => {
  const { writes, fail } = await setup(page)
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('button', { name: '预览 离场旧版', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('文件缺失')
  await page.getByLabel('资源镜头').selectOption('s1')
  await expect(page.getByText('离场旧版', { exact: true })).toHaveCount(0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.screenshot({ path: info.outputPath('video-resources-mobile.png'), fullPage: true })
  fail()
  await page.getByRole('button', { name: '刷新资源' }).click()
  await expect(page.getByRole('alert')).toContainText('资源列表读取失败')
  expect(writes).toEqual([])
})

test('local video actually plays and downloads without provider requests', async ({ page }, info) => {
  const clip = info.outputPath('offline.mp4')
  execFileSync('ffmpeg', ['-v', 'error', '-y', '-f', 'lavfi', '-i',
    'testsrc2=size=96x160:rate=12:duration=2', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', clip])
  // Browser downloads bypass route interception, so serve synthetic bytes locally.
  const content = readFileSync(clip)
  const server = createServer((req, res) => {
    res.setHeader('Content-Type', 'video/mp4')
    res.setHeader('Content-Length', content.length)
    if (req.url?.includes('download=true')) res.setHeader('Content-Disposition', 'attachment; filename="video.mp4"')
    res.end(content)
  })
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve))
  const address = server.address()
  if (!address || typeof address === 'string') throw new Error('Fixture server has no port')
  try {
    const { writes } = await setup(page, entries, `http://127.0.0.1:${address.port}/media.mp4`)
    await page.getByRole('button', { name: '预览 推门旧版', exact: true }).click()
    const video = page.getByLabel('历史视频预览')
    await expect.poll(() => video.evaluate((element: HTMLVideoElement) => element.readyState)).toBeGreaterThanOrEqual(2)
    await video.evaluate((element: HTMLVideoElement) => element.play())
    await expect.poll(() => video.evaluate((element: HTMLVideoElement) => element.currentTime)).toBeGreaterThan(0)
    await page.screenshot({ path: info.outputPath('video-resources-desktop.png'), fullPage: true })
    await page.getByRole('button', { name: '下载 推门旧版', exact: true }).click()
    const downloading = page.waitForEvent('download')
    await page.getByRole('link', { name: '保存视频文件' }).click()
    const download = await downloading
    const downloaded = info.outputPath('downloaded.mp4')
    await download.saveAs(downloaded)
    expect(readFileSync(downloaded).equals(readFileSync(clip))).toBe(true)
    expect(writes).toEqual([])
  } finally {
    server.closeAllConnections()
    await new Promise<void>((resolve, reject) => server.close(error => error ? reject(error) : resolve()))
  }
})

test('pagination and empty filters do not sign all historical videos', async ({ page }) => {
  const many = Array.from({ length: 26 }, (_, i) => ({ ...entries[1], id: `old-${i}`, title: `历史视频 ${i}` }))
  const { accesses, writes } = await setup(page, many)
  await expect(page.getByText('共 26 个视频')).toBeVisible()
  await expect(page.locator('.resource-card')).toHaveCount(24)
  await page.getByRole('button', { name: '下一页' }).click()
  await expect(page.locator('.resource-card')).toHaveCount(2)
  await expect(page.getByText('第 2 页')).toBeVisible()
  await page.getByLabel('资源类型').selectOption('export')
  await expect(page.getByText('当前筛选下没有视频。已有的视频会在这里保留记录。')).toBeVisible()
  await expect(page.getByText('第 1 页')).toBeVisible()
  expect(accesses).toEqual([])
  expect(writes).toEqual([])
})
