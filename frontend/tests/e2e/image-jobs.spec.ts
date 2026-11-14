import { expect, test } from '@playwright/test'

test('refresh restores unknown image submission and recovery never clicks generate', async ({ page }) => {
  const writes: string[] = []
  let job = { id: 'ijob-1', characterId: 'c1', purpose: 'views', status: 'unknown', createdAt: '2026-09-21', updatedAt: '1', completedSteps: ['front'], callsStarted: 2, canRecover: false, taskId: '' }
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname
    if (route.request().method() !== 'GET') {
      writes.push(path)
      expect(path).toContain('/image-jobs/ijob-1/recover')
      job = { ...job, status: 'polling', canRecover: false, updatedAt: '3' }
      return route.fulfill({ status: 202, json: job })
    }
    if (path.endsWith('/image-jobs')) return route.fulfill({ json: { items: [job] } })
    if (path.endsWith('/characters')) return route.fulfill({ json: [{ id: 'c1', name: '小雨', appearance: '短发', clothing: '蓝衣', personality: '沉静', voice: {}, referenceImagePrompt: '' }] })
    if (path === '/api/projects/p1') return route.fulfill({ json: { project: { id: 'p1', version: 2 }, script: { scenes: [], shots: [] }, jobs: [], creditLedger: [], visualAssets: [], audioAssets: [], lipSyncAssets: [], timelines: {} } })
    return route.fulfill({ json: {} })
  })
  await page.addInitScript(() => localStorage.setItem('comicflow-project-id', 'p1'))
  await page.goto('/')
  await page.getByRole('button', { name: '角色', exact: true }).click()
  await expect(page.getByLabel('图片生成进度')).toContainText('提交结果未知')
  await expect(page.getByRole('button', { name: '生成图片', exact: true })).toBeDisabled()
  await page.reload()
  await page.getByRole('button', { name: '角色', exact: true }).click()
  await expect(page.getByLabel('图片生成进度')).toContainText('提交结果未知')
  expect(writes).toEqual([])
  job = { ...job, status: 'recoverable', canRecover: true, taskId: 'provider-task-2', updatedAt: '2' }
  await expect(page.getByRole('button', { name: '恢复已有图片作业' })).toBeVisible()
  await page.getByRole('button', { name: '恢复已有图片作业' }).click()
  await expect(page.getByLabel('图片生成进度')).toContainText('正在查询图片结果')
  expect(writes).toEqual(['/api/projects/p1/image-jobs/ijob-1/recover'])
})
