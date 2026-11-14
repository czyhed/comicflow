import { expect, test } from '@playwright/test'
import type { Script } from '../../src/types'
import { textStreamServer } from '../helpers/text-stream-server'

test('split displays actual content before completion and preserves failure diagnostics', async ({ page }, info) => {
  await page.route('**/api/**', route => route.fulfill({ json: {} }))
  await page.route('**/api/projects/streaming', route => route.fulfill({ json: {
    project: { id: 'streaming', version: 2, generatedStoryText: '雨夜，一名女孩在车站寻找姐姐。' },
    script: null, jobs: [], visualAssets: [], audioAssets: [], timelines: {},
  } }))
  await page.addInitScript(() => localStorage.setItem('comicflow-project-id', 'streaming'))
  const stream = await textStreamServer(page, '**/api/projects/streaming/script/preview',
    '{"title":"雨夜归途","shots":[{"visualDescription":"女孩撑伞走向站台')
  try {
    await page.goto('/')
    await page.locator('[aria-label="工作区导航"] button[aria-label="剧本"]').click()
    await page.getByRole('button', { name: '拆分为剧本', exact: true }).click()
    await expect(page.getByLabel('实时生成内容')).toContainText('女孩撑伞走向站台')
    await expect(page.getByRole('region', { name: '剧本拆分预览' })).toHaveCount(0)
    await expect(page.getByRole('button', { name: '正在拆分…', exact: true })).toBeDisabled()
    await page.screenshot({ path: info.outputPath('split-streaming.png'), fullPage: true })
    await page.setViewportSize({ width: 390, height: 844 })
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    stream.finish({ type: 'error', error: {
      error: 'PROVIDER_INVALID_RESPONSE', stage: 'script_split', reason: 'output_truncated',
    } })
    await expect(page.getByRole('alert')).toContainText('未自动重试')
    await expect(page.getByText('雨夜，一名女孩在车站寻找姐姐。', { exact: true })).toBeVisible()
    expect(stream.calls()).toBe(1)
  } finally { await stream.close() }
})

for (const entry of ['editor', 'import', 'automatic'] as const) {
  test(`${entry} preview commits exact content without regenerating and survives refresh`, async ({ page }) => {
    const script: Script = {
      title: '待确认的新剧本',
      scenes: [{ id: 's1', title: '雨夜车站', time: '深夜', location: '站台', narrativeGoal: '寻找姐姐', conflict: '错过末班车', turningPoint: '姐姐现身', shotIds: ['a', 'b', 'c'] }],
      shots: ['a', 'b', 'c'].map((id, index) => ({ id, sceneId: 's1', order: index + 1, title: `新镜头${index + 1}`, action: '回头', emotion: '紧张', shotSize: '近景', durationSec: 10, visualDescription: `画面${index + 1}`, dialogue: `对白${index + 1}`, narration: `旁白${index + 1}` })),
    }
    let stored: Script | undefined = entry === 'editor' ? { ...script, title: '旧剧本', scenes: [{ id: 'old', title: '旧场景', shotIds: [] }], shots: [] } : undefined
    let version = 2
    let previews = 0
    let writes = 0
    let splitCalls = 0
    const project = () => ({ id: 'preview-project', stage: stored ? 'awaiting-confirmation' : 'story-generated', version, generatedStoryText: '已有故事足够长，等待拆分。', input: { mode: entry === 'automatic' ? 'automatic' : 'import_story', durationSec: 60, story: '已有故事足够长，等待拆分。', inputType: 'story' } })
    const snapshot = () => ({ project: project(), script: stored, jobs: [], creditLedger: [], visualAssets: [], audioAssets: [], lipSyncAssets: [], timelines: {} })
    await page.route('**/api/**', route => route.fulfill({ json: {} }))
    await page.route('**/api/provider-config', route => route.fulfill({ json: { text: { configured: false, enabled: false, apiKeyMasked: '' } } }))
    await page.route('**/api/projects/preview-project', route => route.fulfill({ json: snapshot() }))
    await page.route('**/api/projects', route => route.fulfill({ json: { project: project(), guestSession: { id: 'guest', projectId: 'preview-project' } } }))
    await page.route('**/api/projects/preview-project/script/split', route => { splitCalls++; return route.fulfill({ status: 500, json: { error: 'MUST_NOT_REGENERATE' } }) })
    await page.route('**/api/projects/preview-project/script/preview', async route => {
      if (route.request().method() === 'POST') {
        previews++
        return route.fulfill({ json: { expectedVersion: version, script, summary: { scenes: 1, shots: 3, dialogue: 3, narration: 3, issues: [] }, sceneDetails: [] } })
      }
      const body = route.request().postDataJSON()
      expect(body.script).toEqual(script)
      expect(body.expectedVersion).toBe(2)
      stored = body.script
      version++
      writes++
      return route.fulfill({ json: { project: project(), script: stored } })
    })
    if (entry !== 'import') await page.addInitScript(() => localStorage.setItem('comicflow-project-id', 'preview-project'))
    await page.goto('/')
    if (entry === 'import') await page.getByText('导入内容并整理', { exact: true }).click()
    else await page.locator('[aria-label="工作区导航"] button[aria-label="剧本"]').click()
    await page.getByRole('button', { name: entry === 'editor' ? '重新拆分剧本' : '拆分为剧本', exact: true }).click()
    const preview = page.getByRole('region', { name: '剧本拆分预览' })
    await expect(preview).toBeVisible()
    for (const text of ['新镜头1', '新镜头2', '新镜头3', '站台', '寻找姐姐', '对白3', '旁白3']) await expect(preview).toContainText(text)
    expect(writes).toBe(0)
    await preview.getByRole('button', { name: '确认并进入剧本编辑器' }).first().click()
    await expect(page.getByLabel('剧本标题', { exact: true })).toHaveValue('待确认的新剧本')
    for (const id of ['a', 'b', 'c']) await expect(page.getByLabel(`镜头标题-${id}`, { exact: true })).toHaveCount(1)
    await expect(page.getByLabel('场景-location')).toHaveValue('站台')
    expect(previews).toBe(1)
    expect(writes).toBe(1)
    expect(splitCalls).toBe(0)
    await page.reload()
    await page.locator('[aria-label="工作区导航"] button[aria-label="剧本"]').click()
    await expect(page.getByLabel('镜头标题-c')).toHaveValue('新镜头3')
    await page.screenshot({ path: `test-results/${entry}-preview-editor.png`, fullPage: true })
  })
}
