import { expect, test } from '@playwright/test'

test('one image action routes each chosen mode and keeps secondary content collapsed', async ({ page }, info) => {
  // Plain HTTP on the deployed server has getRandomValues but no randomUUID.
  await page.addInitScript(() => Object.defineProperty(crypto, 'randomUUID', { value: undefined }))
  const purposes: string[] = []
  const card = { id: 'c1', name: '小雨', appearance: '短发', clothing: '蓝外套', personality: '沉静', voice: {},
    referenceImageUrl: 'https://offline.invalid/main.png', referenceImageMediaType: 'image',
    referenceBoard: { id: 'board', status: 'approved', url: 'https://offline.invalid/board.png' } }
  await page.route('https://offline.invalid/**', route => route.fulfill({ status: 204 }))
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname
    if (route.request().method() !== 'GET') {
      expect(path).toBe('/api/projects/compact/characters/c1/image-jobs')
      purposes.push(route.request().postDataJSON().purpose)
      return route.fulfill({ status: 202, json: { id: 'job-' + purposes.length } })
    }
    if (path.endsWith('/image-jobs')) return route.fulfill({ json: { items: [{ id: 'closed', characterId: 'c1', purpose: 'board', status: 'cancelled', error: 'PROVIDER_UNAVAILABLE', errorDetail: { transportError: 'ReadError' }, createdAt: '2026-09-21', updatedAt: '1', completedSteps: [], callsStarted: 1, canRecover: false }] } })
    if (path.endsWith('/characters')) return route.fulfill({ json: [card] })
    if (path === '/api/projects/compact') return route.fulfill({ json: { project: { id: 'compact', version: 2 }, script: { scenes: [], shots: [] }, jobs: [], visualAssets: [], audioAssets: [], timelines: {} } })
    return route.fulfill({ json: {} })
  })
  await page.addInitScript(() => localStorage.setItem('comicflow-project-id', 'compact'))
  await page.goto('/')
  await page.getByRole('button', { name: '角色', exact: true }).click()
  const mode = page.getByLabel('图片生成方式')
  const generate = page.getByRole('button', { name: '生成图片', exact: true })
  await expect(mode).toHaveValue('text-board')
  await expect(generate).toBeEnabled()
  await expect(page.getByLabel('已确认角色参考板').getByRole('img')).toBeVisible()
  await expect(page.getByRole('img', { name: '小雨已确认参考图' })).not.toBeVisible()
  await expect(page.getByLabel('角色提示词用途')).not.toBeVisible()
  await expect(page.getByLabel('角色参考图提示词', { exact: true })).not.toBeVisible()
  await expect(page.getByText('错误代码：PROVIDER_UNAVAILABLE', { exact: true })).not.toBeVisible()
  await expect(page.getByText('本地图片作业已关闭，未重新提交。', { exact: false })).not.toBeVisible()
  await mode.selectOption('board')
  await expect(page.getByLabel('角色参考图生成')).toContainText('已确认主图')
  await mode.selectOption('candidate')
  expect(purposes).toEqual([])
  await generate.click()
  await expect.poll(() => purposes.length).toBe(1)
  await expect(generate).toBeEnabled()
  await mode.selectOption('board')
  await generate.click()
  await expect(generate).toBeEnabled()
  await mode.selectOption('text-board')
  await generate.click()
  await expect(generate).toBeEnabled()
  expect(purposes).toEqual(['candidate', 'board', 'text-board'])
  await page.getByText('生成记录（1）', { exact: true }).click()
  await expect(page.getByText('本地图片作业已关闭，未重新提交。', { exact: false })).toBeVisible()
  await page.getByText('查看错误详情', { exact: true }).click()
  await expect(page.getByText('网络异常类型：ReadError')).toBeVisible()
  await page.reload()
  await page.getByRole('button', { name: '角色', exact: true }).click()
  await expect(mode).toHaveValue('text-board')
  await expect(page.getByText('网络异常类型：ReadError')).not.toBeVisible()
  expect(purposes).toHaveLength(3)
  await page.screenshot({ path: info.outputPath('character-compact-desktop.png'), fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.screenshot({ path: info.outputPath('character-compact-mobile.png'), fullPage: true })
})
