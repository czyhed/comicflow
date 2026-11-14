import { expect, test } from '@playwright/test'

test.beforeEach(async ({ page }) => {
  await page.route('**/api/**', route => route.abort('blockedbyclient'))
})

const script = {
  title: '雨夜的最后一班车',
  scenes: [{ id: 'scene-1', title: '车站', shotIds: ['shot-1'] }],
  shots: [{
    id: 'shot-1', order: 1, title: '车窗回头', action: '姐姐回头', emotion: '惊讶',
    shotSize: '中景', durationSec: 30, visualDescription: '车窗后的姐姐', dialogue: '你终于来了。',
  }],
}

test('creator can generate visual audio and composition assets from the new workspace', async ({ page }) => {
  await page.route('**/api/**', route => route.abort('blockedbyclient'))
  let version = 1
  let visualGenerated = false
  let visualAdopted = false
  let compositionQueued = false
  let exportReady = false
  await page.route('**/api/projects', (route) => route.fulfill({
    json: { project: { id: 'prj_flow', stage: 'story', version }, guestSession: { id: 'gst_flow', projectId: 'prj_flow' } },
  }))
  await page.route('**/api/projects/prj_flow/story', async (route) => {
    version = 2
    await route.fulfill({ json: { project: { id: 'prj_flow', stage: 'story-generated', version, generatedStoryText: '自动故事文本。' }, storyText: '自动故事文本。' } })
  })
  let previewGenerations = 0
  let previewCommits = 0
  await page.route('**/api/projects/prj_flow/script/preview', async (route) => {
    if (route.request().method() === 'PUT') {
      previewCommits += 1
      version = 3
      await route.fulfill({ json: { project: { id: 'prj_flow', stage: 'script-completed', version }, script } })
      return
    }
    previewGenerations += 1
    await route.fulfill({ json: { script, summary: { scenes: 1, shots: 1, dialogue: 1, narration: 0, issues: [] }, expectedVersion: 2 } })
  })
  await page.route('**/api/projects/prj_flow', (route) => route.fulfill({
    json: {
      project: {
        id: 'prj_flow', stage: version >= 3 ? 'storyboard-ready' : 'story-generated', version,
        generatedStoryText: version >= 3 ? undefined : '自动故事文本。',
        exportManifest: exportReady ? { files: ['video.mp4', 'cover.jpg', 'subtitles.srt'] } : null,
      },
      script: version >= 3 ? script : null,
      jobs: compositionQueued ? [{ id: 'job-1', type: 'composition', status: 'queued', progress: 0 }] : [],
      visualAssets: visualGenerated ? [{ id: 'visual-1', shotId: 'shot-1', valid: visualAdopted,
        status: visualAdopted ? 'current' : 'candidate', mediaType: 'video',
        downloadUrl: 'https://offline.invalid/candidate.mp4' }] : [],
      audioAssets: [{ id: 'audio-1', shotId: 'shot-1', durationMs: 6000, valid: true }],
      lipSyncAssets: [{ id: 'lip-1', shotId: 'shot-1', startMs: 0, endMs: 6000, valid: true }],
      timelines: {
        'shot-1': {
          shotId: 'shot-1', durationMs: 6000, visualAssetId: 'visual-1',
          actionTrack: [{ type: '望向窗外', startMs: 0, endMs: 3000 }, { type: '姐姐回头', startMs: 3000, endMs: 6000 }],
          expressionTrack: [{ type: '平静', startMs: 0, endMs: 3000 }, { type: '惊讶', startMs: 3000, endMs: 6000 }],
          cameraTrack: [{ type: '缓慢推进', startMs: 0, endMs: 6000 }],
          dialogue: [{ text: '你终于来了。', startMs: 0, endMs: 6000 }],
          subtitle: [{ text: '你终于来了。', startMs: 0, endMs: 6000 }],
          lipSyncTrack: [{ assetId: 'lip-1', startMs: 0, endMs: 6000 }],
        },
      },
      exportManifest: exportReady ? { files: ['video.mp4', 'cover.jpg', 'subtitles.srt'] } : null,
    },
  }))
  const videoJob = { id: 'vjob-flow', projectId: 'prj_flow', shotId: 'shot-1',
    status: 'succeeded', createdAt: '2026-09-19T00:00:00Z', updatedAt: '2026-09-19T00:00:00Z',
    callsStarted: { text: 0, video: 1 }, history: [], parameters: {}, canRecover: false, canLinkTask: false,
    result: { assetId: 'visual-1', adopted: false, projectVersion: 3 } }
  await page.route('**/api/projects/prj_flow/video-jobs/vjob-flow/adopt', route => {
    visualAdopted = true
    videoJob.result.adopted = true
    return route.fulfill({ json: videoJob })
  })
  await page.route('**/api/projects/prj_flow/video-jobs', route => route.fulfill({ json: { items: visualGenerated ? [videoJob] : [] } }))
  await page.route('**/api/projects/prj_flow/shots/shot-1/video-jobs', (route) => {
    visualGenerated = true
    return route.fulfill({
      status: 202, json: videoJob,
    })
  })
  await page.route('**/api/projects/prj_flow/shots/shot-1/visual/preflight', route => route.fulfill({
    json: { ready: true, fingerprint: 'a'.repeat(64), model: 'Mock', parameters: {},
      references: [], prompt: null, calls: { text: 0, video: 0 }, price: null, errors: [], warnings: [] },
  }))
  await page.route('**/api/projects/prj_flow/shots/shot-1/audio', (route) => route.fulfill({
    json: { asset: { id: 'audio-1', shotId: 'shot-1' }, lipSync: { id: 'lip-1' }, timeline: {}, projectVersion: version },
  }))
  await page.route('**/api/projects/prj_flow/composition', (route) => {
    compositionQueued = true
    exportReady = true
    return route.fulfill({ status: 202, json: { id: 'job-1', status: 'queued' } })
  })
  let exportRead = false
  await page.route('**/api/projects/prj_flow/export', (route) => {
    exportRead = true
    return route.fulfill({ json: { projectId: 'prj_flow', files: ['video.mp4', 'cover.jpg', 'subtitles.srt'], format: 'h264-aac-1080x1920-30fps' } })
  })

  await page.goto('/')
  await page.getByText('全自动').click()
  await page.getByRole('button', { name: '生成故事文本' }).click()
  await page.getByRole('button', { name: '进入剧本模块拆分' }).click()
  await page.getByRole('button', { name: '拆分为剧本' }).click()
  await expect(page.getByRole('region', { name: '剧本拆分预览' })).toBeVisible()
  expect(previewGenerations).toBe(1)
  expect(previewCommits).toBe(0)
  await page.getByRole('button', { name: '确认并进入剧本编辑器' }).first().click()
  await expect(page.getByText('剧本编辑器', { exact: true })).toBeVisible()
  expect(previewCommits).toBe(1)
  await page.getByRole('button', { name: '画面' }).click()
  await expect(page.getByText('动态镜头预览')).toBeVisible()
  await page.getByRole('button', { name: '生成当前镜头' }).click()
  await expect.poll(() => visualGenerated).toBe(true)
  await page.getByRole('button', { name: '采用此候选视频' }).click()
  await expect.poll(() => visualAdopted).toBe(true)
  await page.getByRole('button', { name: '声音' }).click()
  await expect(page.getByText('音画时间轴')).toBeVisible()
  const playhead = page.getByRole('slider', { name: '镜头播放头' })
  await expect(playhead).toHaveAttribute('max', '6000')
  await playhead.fill('3000')
  await expect(page.getByText('00:03.0 / 00:06.0')).toBeVisible()
  await expect(page.locator('.preview-frame small')).toContainText('当前动作：姐姐回头')
  await expect(page.locator('.preview-frame small')).toContainText('当前表情：惊讶')
  await expect(page.locator('[data-track="action"] .track-playhead')).toHaveAttribute('style', /50%/)
  await expect(page.locator('[data-track="lipsync"] .track-playhead')).toHaveAttribute('style', /50%/)
  await page.getByRole('button', { name: '重新生成对白与口型' }).click()
  await page.getByRole('button', { name: '导出', exact: true }).click()
  await expect(page.getByText('导出包预览')).toBeVisible()
  await page.getByRole('button', { name: '开始合成' }).click()
  await expect(page.getByText('导出包已就绪')).toBeVisible()
  await expect(page.getByRole('button', { name: '下载导出包' })).toBeVisible()
  await Promise.all([
    page.waitForRequest('**/api/projects/prj_flow/export'),
    page.getByRole('button', { name: '下载导出包' }).click(),
  ])
  expect(exportRead).toBe(true)
})

test('automatic production exposes persisted session controls', async ({ page }) => {
  let status = 'running'
  let stage = 'storyboard-ready'
  const project = { id: 'prj_auto', stage, version: 1, input: { inputType: 'story', story: '自动生产测试故事', durationSec: 60, mode: 'automatic' } }
  await page.route('**/api/projects/prj_auto', (route) => route.fulfill({ json: { project, jobs: [], creditLedger: [] } }))
  await page.route('**/api/projects/prj_auto/generation-session', (route) => route.fulfill({ json: { id: 'gen_auto', projectId: 'prj_auto', mode: 'automatic', stage, status, retryCount: 0 } }))
  await page.route('**/api/projects/prj_auto/generation-session/pause', async (route) => { status = 'paused'; await route.fulfill({ json: { id: 'gen_auto', projectId: 'prj_auto', mode: 'automatic', stage, status, retryCount: 0 } }) })
  await page.route('**/api/projects/prj_auto/generation-session/resume', async (route) => { status = 'running'; await route.fulfill({ json: { id: 'gen_auto', projectId: 'prj_auto', mode: 'automatic', stage, status, retryCount: 0 } }) })
  await page.route('**/api/projects/prj_auto/generation-session/advance', async (route) => { stage = 'assets-ready'; await route.fulfill({ json: { id: 'gen_auto', projectId: 'prj_auto', mode: 'automatic', stage, status, retryCount: 0 } }) })

  await page.goto('/')
  await page.evaluate(() => localStorage.setItem('comicflow-project-id', 'prj_auto'))
  await page.reload()
  await expect(page.getByText('剧本已确认 · 处理中')).toBeVisible()
  await page.getByRole('button', { name: '暂停' }).click()
  await expect(page.getByText('剧本已确认 · 已暂停')).toBeVisible()
  await page.getByRole('button', { name: '继续' }).click()
  await expect(page.getByText('剧本已确认 · 处理中')).toBeVisible()
  await page.getByRole('button', { name: '推进' }).click()
  await expect(page.getByText('素材已就绪 · 处理中')).toBeVisible()
})

test('confirming a script refreshes the automatic production session controls', async ({ page }) => {
  let confirmed = false
  let sessionReads = 0
  const script = {
    title: '确认同步测试',
    scenes: [{ id: 'scene-1', title: '车站', shotIds: ['shot-1'] }],
    shots: [{
      id: 'shot-1', order: 1, title: '回头', action: '回头', emotion: '惊讶',
      shotSize: '特写', durationSec: 30, visualDescription: '姐姐回头', dialogue: '你来了。', narration: '',
    }],
  }
  const project = {
    id: 'prj_confirm_sync',
    stage: 'awaiting-confirmation',
    version: 3,
    input: { inputType: 'story', story: '自动生产测试故事', durationSec: 60, mode: 'automatic' },
  }
  await page.addInitScript(() => localStorage.setItem('comicflow-project-id', 'prj_confirm_sync'))
  await page.route('**/api/projects/prj_confirm_sync', (route) => route.fulfill({ json: {
    project: { ...project, stage: confirmed ? 'storyboard-ready' : project.stage, version: confirmed ? 4 : project.version },
    script,
    jobs: [],
    visualAssets: [],
    audioAssets: [],
    lipSyncAssets: [],
    creditLedger: [],
  } }))
  await page.route('**/api/projects/prj_confirm_sync/generation-session', (route) => {
    sessionReads += 1
    return route.fulfill({ json: {
      id: 'gen_confirm_sync', projectId: 'prj_confirm_sync', mode: 'automatic',
      stage: confirmed ? 'storyboard-ready' : 'script-completed', status: 'ready', retryCount: 0,
    } })
  })
  await page.route('**/api/projects/prj_confirm_sync/script/confirm', async (route) => {
    confirmed = true
    await route.fulfill({ json: {
      project: {
        ...project,
        stage: 'storyboard-ready',
        version: 4,
        generationSession: {
          id: 'gen_confirm_sync', projectId: 'prj_confirm_sync', mode: 'automatic',
          stage: 'storyboard-ready', status: 'ready', retryCount: 0,
        },
      },
      script,
    } })
  })

  await page.goto('/')
  await page.getByRole('button', { name: '剧本', exact: true }).first().click()
  await expect(page.getByText('剧本编辑器', { exact: true })).toBeVisible()
  await expect(page.getByText('剧本待确认 · 等待操作', { exact: true })).toBeVisible()
  // Before confirmation, the advance button is replaced by a hint
  await expect(page.getByText('先到「剧本」工作区拆分并确认')).toBeVisible()
  await page.getByRole('button', { name: '确认剧本并生成分镜', exact: true }).click()

  await expect(page.getByRole('button', { name: '推进', exact: true })).toBeVisible()
  await expect(page.getByText('剧本已确认 · 等待操作', { exact: true })).toBeVisible()
  expect(sessionReads).toBeGreaterThan(0)
})
