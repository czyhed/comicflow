import { expect, test } from '@playwright/test'

const profile = { presetId: 'anime-2d', revision: 1, name: '日系二维动画', medium: 'animation-2d',
  description: '稳定线稿、赛璐璐阴影与干净色块。', rendering: '线稿稳定，赛璐璐阴影',
  lighting: '色块清晰', motion: '轮廓稳定', avoid: '避免照片纹理' }
const catalog = [
  { ...profile, presetId: 'cinematic-realism', name: '真人电影写实', description: '自然肤质、真实材质与克制的摄影光影。' },
  { ...profile, presetId: 'guofeng-3d', name: '国风三维动画', description: '三维角色体积、精细服饰与统一动画材质。' },
  profile,
  { ...profile, presetId: 'guofeng-painted', name: '国风厚涂', description: '细腻笔触、层叠色彩与绘画式体积。' },
  { ...profile, presetId: 'ink-animation', name: '水墨动画', description: '墨色浓淡、留白和可辨识的笔触。' },
  { ...profile, presetId: 'graphic-comic', name: '美式漫画', description: '明确轮廓、图形化阴影与鲜明对比。' },
]

test('style selection is free, saved at creation and visible after reload', async ({ page }, info) => {
  const writes: { path: string; body: Record<string, unknown> }[] = []
  const project = { id: 'style-project', version: 2, stage: 'story-generated',
    generatedStoryText: '女子冒雨走进便利店，询问失踪的姐姐。',
    input: { mode: 'automatic' }, visualStyleProfile: profile }
  await page.route('**/api/**', async route => {
    const req = route.request(), path = new URL(req.url()).pathname
    if (req.method() === 'POST') writes.push({ path, body: req.postDataJSON() })
    if (path === '/api/visual-styles') return route.fulfill({ json: { items: catalog } })
    if (path === '/api/provider-config') return route.fulfill({ json: { text: { configured: false } } })
    if (path === '/api/projects' && req.method() === 'POST') return route.fulfill({ json: {
      project, guestSession: { id: 'guest', projectId: project.id },
    } })
    if (path.endsWith('/story')) return route.fulfill({ json: { project, storyText: project.generatedStoryText } })
    if (path === '/api/projects/style-project') return route.fulfill({ json: {
      project, script: null, jobs: [], visualAssets: [], audioAssets: [], timelines: {},
    } })
    return route.fulfill({ json: {} })
  })
  await page.goto('/')
  await page.getByRole('combobox', { name: '选择新项目画风', exact: true }).selectOption('anime-2d')
  await expect(page.getByText(profile.description, { exact: true })).toBeVisible()
  expect(writes).toEqual([])
  await page.getByRole('button', { name: '生成故事文本', exact: true }).click()
  await expect(page.getByText('当前项目画风：日系二维动画 · v1')).toBeVisible()
  expect(writes.find(w => w.path === '/api/projects')?.body.stylePresetId).toBe('anime-2d')
  await page.reload()
  await expect(page.getByText('当前项目画风：日系二维动画 · v1')).toBeVisible()
  await page.getByRole('region', { name: '项目风格库' }).screenshot({ path: info.outputPath('style-desktop.png') })
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(page.getByRole('combobox', { name: '选择新项目画风', exact: true })).toHaveValue('')
  await page.getByRole('combobox', { name: '选择新项目画风', exact: true }).selectOption('anime-2d')
  await expect(page.getByRole('combobox', { name: '选择新项目画风', exact: true })).toHaveValue('anime-2d')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.getByRole('region', { name: '项目风格库' }).screenshot({ path: info.outputPath('style-mobile.png') })
  await page.setViewportSize({ width: 1024, height: 600 })
  const picker = page.getByRole('region', { name: '项目风格库' })
  expect((await picker.boundingBox())!.height).toBeLessThan(340)
  const generate = page.getByRole('button', { name: '生成故事文本', exact: true })
  await generate.scrollIntoViewIfNeeded()
  const bounds = (await generate.boundingBox())!
  expect(bounds.y).toBeGreaterThanOrEqual(0)
  expect(bounds.y + bounds.height).toBeLessThanOrEqual(600)
  expect(writes.map(w => w.path)).toEqual(['/api/projects', '/api/projects/style-project/story'])
})

test('catalog failure has explicit retry and keeps legacy choice available', async ({ page }) => {
  let failed = true
  await page.route('**/api/**', route => {
    if (new URL(route.request().url()).pathname === '/api/provider-config') {
      return route.fulfill({ json: { text: { configured: false } } })
    }
    if (new URL(route.request().url()).pathname === '/api/visual-styles') {
      return failed ? route.fulfill({ status: 503, json: { error: 'OFFLINE' } })
        : route.fulfill({ json: { items: [profile] } })
    }
    return route.fulfill({ json: {} })
  })
  await page.goto('/')
  await expect(page.getByText('风格库读取失败，可重试或保持未统一设置。')).toBeVisible()
  failed = false
  await page.getByRole('button', { name: '重新读取风格库' }).click()
  await expect(page.getByRole('combobox', { name: '选择新项目画风', exact: true }).getByRole('option', { name: '日系二维动画', exact: true })).toBeAttached()
  await expect(page.getByRole('combobox', { name: '选择新项目画风', exact: true })).toHaveValue('')
})
