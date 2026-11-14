import { expect, test, type Page } from '@playwright/test'

function fixture(provider = 'minimax') {
  return {
    project: { id: 'prj_sound', stage: 'storyboard-ready', version: 4,
      input: { inputType: 'story', mode: 'import_script', story: '两人在雨夜告别。', durationSec: 30 } },
    script: { title: '原声验收', scenes: [
      { id: 'sc1', title: '车站', shotIds: ['s1'] },
      { id: 'sc2', title: '列车', shotIds: ['s2'] },
    ],
      shots: [
        { id: 's1', order: 1, title: '告别', dialogue: '女主：“明天见。”', narration: '',
          action: '挥手', emotion: '不舍', durationSec: 15, shotSize: '中景', visualDescription: '车站挥手' },
        { id: 's2', order: 2, title: '离开', dialogue: '', narration: '列车驶入雨幕。',
          action: '转身', emotion: '平静', durationSec: 15, shotSize: '远景', visualDescription: '列车离开' },
      ] },
    visualAssets: ['s1', 's2'].map((shotId, index) => ({
      id: `v${index}`, shotId, provider, mediaType: 'video', valid: true,
      downloadUrl: `/fixtures/${shotId}.mp4`,
    })),
    audioAssets: [] as Array<Record<string, unknown>>,
    lipSyncAssets: [], timelines: {}, creditLedger: [],
    jobs: [] as Array<Record<string, unknown>>,
    exportManifest: null as null | { files: string[] },
  }
}

test('trial trimming changes only composition parameters and fits desktop and mobile', async ({ page }, info) => {
  const { data, writes } = await setup(page)
  let body: Record<string, unknown> | undefined
  await page.route('**/api/projects/prj_sound/composition', async route => {
    writes.push('/api/projects/prj_sound/composition')
    body = route.request().postDataJSON()
    data.jobs.push({ id: 'trim-trial', type: 'composition', status: 'queued', shotIds: ['s1', 's2'] })
    await route.fulfill({ status: 202, json: { id: 'trim-trial', status: 'queued' } })
  })
  await page.getByRole('button', { name: '导出', exact: true }).click()
  await page.getByRole('tab', { name: '选中镜头', exact: true }).click()
  await page.getByLabel('裁剪入点').fill('0.4')
  await page.getByLabel('裁剪出点').fill('14.5')
  await page.screenshot({ path: info.outputPath('trim-desktop.png'), fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.screenshot({ path: info.outputPath('trim-mobile.png'), fullPage: true })
  await page.getByRole('button', { name: '合成选中镜头', exact: true }).click()
  await expect.poll(() => body).toBeTruthy()
  expect(body?.shotIds).toEqual(['s1', 's2'])
  expect(body?.shotTrims).toEqual({ s1: { inSec: .4, outSec: 14.5 } })
  expect(writes).toEqual(['/api/projects/prj_sound/composition'])
  expect(data.script.shots[0].durationSec).toBe(15)
})

async function setup(page: Page, data = fixture()) {
  const writes: string[] = []
  await page.addInitScript(() => {
    localStorage.setItem('comicflow-project-id', 'prj_sound')
    localStorage.removeItem('comicflow-user-id')
  })
  // No request may reach a real backend, storage service or provider.
  await page.route('**/*', route => {
    const url = new URL(route.request().url())
    if (url.origin !== 'http://127.0.0.1:4173') return route.abort()
    if (url.pathname.startsWith('/api/')) {
      if (route.request().method() !== 'GET') writes.push(url.pathname)
      return route.fulfill({ status: 404, json: { error: 'UNEXPECTED_TEST_REQUEST' } })
    }
    if (url.pathname.startsWith('/fixtures/')) return route.fulfill({ status: 404 })
    return route.continue()
  })
  await page.route('**/api/projects/prj_sound', route => route.fulfill({ json: data }))
  await page.route('**/api/projects', route => route.fulfill({ json: { projects: [] } }))
  await page.goto('/')
  return { data, writes }
}

test('manual confirmation does not show cached automatic controls and export has a readable status', async ({ page }) => {
  const data = fixture()
  data.script.shots[0].dialogue = ''
  data.script.shots[0].narration = ''
  await setup(page, data)
  await page.route('**/api/projects/prj_sound/script/confirm', route => route.fulfill({ json: {
    project: { ...data.project, generationSession: { id: 'manual', projectId: 'prj_sound',
      mode: 'import_script', stage: 'storyboard-ready', status: 'ready', retryCount: 0 } }, script: data.script,
  } }))
  await page.getByRole('button', { name: '剧本', exact: true }).click()
  await expect(page.getByLabel('对白-s1', { exact: true })).toHaveValue('')
  await expect(page.getByLabel('旁白-s1', { exact: true })).toHaveValue('')
  await expect(page.getByText('存在缺少对白或旁白的镜头')).toHaveCount(0)
  await page.getByRole('button', { name: '确认剧本并生成分镜' }).click()
  await expect(page.getByText('故事板', { exact: true })).toBeVisible()
  await expect(page.getByLabel('生成会话控制')).toHaveCount(0)
  data.exportManifest = { files: ['video.mp4', 'cover.jpg', 'subtitles.srt'] }
  await page.reload()
  await expect(page.getByLabel('项目制作状态')).toHaveText('成片已就绪')
})

test('storyboard opens the selected shot in its scene editor on a narrow screen without generation', async ({ page }, info) => {
  const { writes } = await setup(page)
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('button', { name: '分镜', exact: true }).click()
  await page.getByRole('button', { name: '02 离开 15s · 远景' }).click()
  await page.getByRole('button', { name: '到剧本编辑当前镜头', exact: true }).click()
  await expect(page.getByLabel('场景标题', { exact: true })).toHaveValue('列车')
  await expect(page.getByLabel('镜头标题-s2')).toHaveValue('离开')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.screenshot({ path: info.outputPath('storyboard-edit-mobile.png'), fullPage: true })
  expect(writes).toEqual([])
})

test('native footage is previewable without a timeline and script text is read-only', async ({ page }, testInfo) => {
  const { writes } = await setup(page)
  await page.getByRole('button', { name: '声音', exact: true }).click()
  await expect(page.getByRole('heading', { name: '声音与字幕' })).toBeVisible()
  await expect(page.locator('video[aria-label="当前镜头原声视频"]')).toHaveAttribute('src', '/fixtures/s1.mp4')
  await expect(page.getByLabel('已保存对白')).toHaveJSProperty('readOnly', true)
  await expect(page.getByLabel('已保存对白')).toHaveValue('女主：“明天见。”')
  await expect(page.getByText('字幕尚未进行语音时间对齐')).toBeVisible()
  await expect(page.getByRole('button', { name: /生成.*配音|重新生成对白与口型/ })).toHaveCount(0)
  await page.getByLabel('镜头选择').selectOption('s2')
  await expect(page.getByLabel('已保存旁白')).toHaveValue('列车驶入雨幕。')
  await expect(page.getByLabel('已保存对白')).toHaveValue('')
  await expect(page.locator('video')).toHaveAttribute('src', '/fixtures/s2.mp4')
  await page.screenshot({ path: testInfo.outputPath('native-audio-desktop.png'), fullPage: true })
  await page.getByRole('button', { name: '到剧本编辑台词' }).click()
  await expect(page.getByText('剧本编辑器', { exact: true })).toBeVisible()
  await expect(page.getByLabel('场景标题', { exact: true })).toHaveValue('列车')
  await expect(page.getByLabel('旁白-s2', { exact: true })).toHaveValue('列车驶入雨幕。')
  expect(writes).toEqual([])
})

test('native composition sends only one composition request and locks while queued', async ({ page }) => {
  const { data, writes } = await setup(page)
  let compositions = 0
  await page.route('**/api/projects/prj_sound/composition', async route => {
    compositions++
    expect(route.request().postDataJSON().expectedVersion).toBe(4)
    data.jobs = [{ id: 'job1', type: 'composition', status: 'queued' }]
    await route.fulfill({ status: 202, json: data.jobs[0] })
  })
  await page.getByRole('button', { name: '导出', exact: true }).click()
  await expect(page.getByRole('button', { name: '开始合成', exact: true })).toBeEnabled()
  await expect(page.getByRole('button', { name: /生成全部|提取视频原声/ })).toHaveCount(0)
  await page.getByRole('button', { name: '开始合成', exact: true }).click()
  await expect(page.getByRole('button', { name: '合成处理中' })).toBeDisabled()
  expect(compositions).toBe(1)
  expect(writes).toEqual([])
})

test('non-native missing voices require explicit audio navigation and errors stay visible', async ({ page }) => {
  const { writes } = await setup(page, fixture('bailian'))
  let calls = 0
  await page.route('**/api/projects/prj_sound/shots/s1/audio', route => {
    calls++
    return route.fulfill({ status: 503, json: { error: 'PROVIDER_UNAVAILABLE' } })
  })
  await page.getByRole('button', { name: '导出', exact: true }).click()
  await expect(page.getByRole('button', { name: '开始合成', exact: true })).toBeDisabled()
  await page.getByRole('button', { name: '去准备独立配音' }).click()
  await expect(page.getByText('独立配音可能调用模型并消耗额度。')).toBeVisible()
  await page.getByRole('button', { name: '生成当前镜头配音' }).click()
  await expect(page.getByRole('alert')).toContainText('模型服务')
  expect(calls).toBe(1)
  expect(writes).toEqual([])
})

test('selected composition works before all shots are ready and survives refresh', async ({ page }, info) => {
  const data = fixture()
  data.visualAssets = data.visualAssets.slice(0, 1)
  const { writes } = await setup(page, data)
  let count = 0
  await page.route('**/api/projects/prj_sound/composition', async route => {
    count++
    expect(route.request().postDataJSON().shotIds).toEqual(['s1'])
    data.jobs = [{ id: 'trial1', type: 'composition', status: 'succeeded', shotIds: ['s1'],
      exportManifest: { files: ['video.mp4', 'cover.jpg', 'subtitles.srt'] } }]
    return route.fulfill({ status: 202, json: data.jobs[0] })
  })
  await page.route('**/api/projects/prj_sound/export?job_id=trial1', route => route.fulfill({
    json: { projectId: 'prj_sound', files: ['video.mp4'], scope: 'selected',
      downloads: { 'video.mp4': '/fixtures/trial.mp4' } },
  }))
  await page.getByRole('button', { name: '导出', exact: true }).click()
  await expect(page.getByRole('button', { name: '开始合成', exact: true })).toBeDisabled()
  await page.getByRole('tab', { name: '选中镜头', exact: true }).click()
  await expect(page.getByRole('checkbox', { name: '合成镜头 1 告别' })).toBeChecked()
  await expect(page.getByRole('checkbox', { name: '合成镜头 2 离开' })).toBeDisabled()
  await page.screenshot({ path: info.outputPath('selected-export-desktop.png'), fullPage: true })
  await page.getByRole('button', { name: '清空', exact: true }).click()
  await expect(page.getByRole('button', { name: '合成选中镜头' })).toBeDisabled()
  await page.getByRole('button', { name: '选择已就绪' }).click()
  await page.getByRole('button', { name: '合成选中镜头' }).click()
  await expect(page.getByRole('button', { name: '下载导出包' })).toBeVisible()
  await page.getByRole('button', { name: '加载成片预览' }).click()
  await expect(page.getByLabel('合成视频预览')).toHaveAttribute('src', '/fixtures/trial.mp4')
  await page.setViewportSize({ width: 390, height: 844 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.screenshot({ path: info.outputPath('selected-export-mobile.png'), fullPage: true })
  await page.reload()
  await page.getByRole('button', { name: '导出', exact: true }).click()
  await page.getByRole('tab', { name: '选中镜头', exact: true }).click()
  await expect(page.getByLabel('已保存试片')).toHaveValue('trial1')
  await page.getByRole('tab', { name: '完整成片', exact: true }).click()
  await expect(page.getByRole('button', { name: '开始合成', exact: true })).toBeDisabled()
  expect(data.exportManifest).toBeNull()
  expect(count).toBe(1)
  expect(writes).toEqual([])
})

test('missing visual navigates to its workspace without generating', async ({ page }) => {
  const data = fixture()
  data.visualAssets = []
  const { writes } = await setup(page, data)
  await page.getByRole('button', { name: '声音', exact: true }).click()
  await page.getByRole('button', { name: '到画面生成当前镜头' }).click()
  await expect(page.getByText('动态镜头预览')).toBeVisible()
  expect(writes.filter(path => !path.endsWith('/visual/preflight'))).toEqual([])
})

test('empty toolbar controls are removed and narrow audio view stays inside viewport', async ({ page }, testInfo) => {
  const { writes } = await setup(page)
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('button', { name: '分镜', exact: true }).click()
  await expect(page.getByRole('button', { name: '资产管理', exact: true })).toHaveCount(0)
  await expect(page.getByRole('checkbox', { name: '我收藏的' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '网格视图' })).toHaveCount(0)
  await page.getByRole('button', { name: '声音', exact: true }).click()
  await expect(page.getByRole('heading', { name: '声音与字幕' })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.screenshot({ path: testInfo.outputPath('native-audio-mobile.png'), fullPage: true })
  expect(writes).toEqual([])
})

test('export previews use saved file URLs and subtitles are not marked aligned', async ({ page }, testInfo) => {
  const data = fixture()
  data.exportManifest = { files: ['video.mp4', 'cover.jpg', 'subtitles.srt'] }
  const { writes } = await setup(page, data)
  let reads = 0
  await page.route('**/api/projects/prj_sound/export', route => {
    reads++
    return route.fulfill({ json: { projectId: 'prj_sound', files: data.exportManifest!.files,
      format: 'h264-aac-1080x1920-30fps', downloads: {
        'video.mp4': '/fixtures/export.mp4', 'cover.jpg': '/fixtures/cover.jpg', 'subtitles.srt': '/fixtures/subtitles.srt',
      } } })
  })
  await page.getByRole('button', { name: '导出', exact: true }).click()
  await expect(page.getByRole('button', { name: '下载导出包' })).toBeVisible()
  await page.getByRole('button', { name: '加载成片预览' }).click()
  await expect(page.getByLabel('合成视频预览')).toHaveAttribute('src', '/fixtures/export.mp4')
  await page.getByRole('tab', { name: '封面' }).click()
  await expect(page.getByAltText('合成视频封面')).toHaveAttribute('src', '/fixtures/cover.jpg')
  await page.getByRole('tab', { name: '字幕' }).click()
  await expect(page.getByRole('link', { name: '查看或下载 SRT 字幕' })).toHaveAttribute('href', '/fixtures/subtitles.srt')
  await expect(page.getByText('字幕来自剧本与镜头时长，尚未进行语音时间对齐。')).toBeVisible()
  expect(reads).toBe(1)
  expect(writes).toEqual([])
  await page.screenshot({ path: testInfo.outputPath('export-desktop.png'), fullPage: true })
})

test('missing native soundtrack is visible as a failed job without offering paid fallback', async ({ page }) => {
  const data = fixture()
  data.jobs = [{ id: 'job1', type: 'composition', status: 'failed', error: 'COMPOSITION_AUDIO_MISSING' }]
  const { writes } = await setup(page, data)
  await page.getByRole('button', { name: '导出', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('未调用配音模型')
  await expect(page.getByRole('button', { name: /生成全部|重新配音/ })).toHaveCount(0)
  expect(writes).toEqual([])
})

test('session controls lock during mutation and show failures', async ({ page }) => {
  const data = fixture()
  data.project.input.mode = 'automatic'
  await setup(page, data)
  await page.route('**/api/projects/prj_sound/generation-session', route => route.fulfill({ json: {
    id: 'gen1', projectId: 'prj_sound', mode: 'automatic', stage: 'storyboard-ready', status: 'running', retryCount: 0,
  } }))
  let finish: () => void = () => {}
  const gate = new Promise<void>(resolve => { finish = resolve })
  let calls = 0
  await page.route('**/api/projects/prj_sound/generation-session/pause', async route => {
    calls++
    await gate
    await route.fulfill({ status: 409, json: { error: 'SESSION_ACTION_INVALID' } })
  })
  await page.reload()
  await page.getByRole('button', { name: '暂停', exact: true }).click()
  await expect(page.getByRole('button', { name: '暂停', exact: true })).toBeDisabled()
  await expect(page.getByRole('button', { name: '推进', exact: true })).toBeDisabled()
  finish()
  await expect(page.getByRole('alert').filter({ hasText: 'SESSION_ACTION_INVALID' })).toBeVisible()
  expect(calls).toBe(1)
})
