import { test, expect } from '@playwright/test'
import { createHash } from 'node:crypto'
import { writeFileSync } from 'node:fs'
import path from 'node:path'

test('real isolated application produces and restores a six-shot film without model charges', async ({ page, request }, info) => {
  const origin = 'http://127.0.0.1:4184'
  const out = path.resolve(process.env.COMICFLOW_VERIFY_OUTPUT || '../var/verification/full-flow-20260921')
  let userId = ''
  async function api(method: string, url: string, data?: unknown) {
    const response = await request.fetch(url, { method, data, headers: userId ? { 'x-user-id': userId } : {} })
    expect(response.ok(), `${method} ${url}: ${await response.text()}`).toBeTruthy()
    return response.json()
  }
  const status = () => api('GET', '/test-control/status')
  await expect.poll(async () => {
    try {
      const response = await request.get('/test-control/status')
      return response.ok() && (await response.json()).ready
    } catch { return false }
  }, { timeout: 60000 }).toBe(true)
  // Actual registry API: adapters share a local fake supplier, with no external route.
  let catalog = await api('GET', '/api/model-registry')
  expect(catalog.revision).toBe(0)
  catalog = await api('POST', '/api/model-registry/connections', {
    revision: catalog.revision, name: 'isolated-fake', baseUrl: 'http://127.0.0.1:18099', apiKey: 'fake-only',
  })
  const connectionId = catalog.connections[0].id
  const bindings: Record<string, string> = {}
  for (const [usage, protocol, model, config] of [
    ['script', 'chat-completions', 'fake-text', { timeoutMs: 30000 }],
    ['image', 'wan-image', 'wan2.2-t2i-flash', { timeoutMs: 30000, size: '1536*1024' }],
    ['image-edit', 'wan26-image', 'wan2.6-image', { timeoutMs: 30000, size: '1536*1024' }],
    ['video', 'compshare-h3', 'MiniMax-H3', { timeoutMs: 30000, resolution: '768P', h3PromptMode: 'context-ir' }],
  ] as const) {
    catalog = await api('POST', '/api/model-registry/models', {
      revision: catalog.revision, name: usage, connectionId, protocol, model, config, enabled: true,
    })
    bindings[usage] = catalog.models.find((m: any) => m.name === usage).id
  }
  bindings.story = bindings.script
  catalog = await api('PUT', '/api/model-registry/bindings', { revision: catalog.revision, bindings })
  expect((await api('GET', '/api/model-registry')).bindings).toEqual(bindings)
  const project = await api('POST', '/api/projects', { inputType: 'story', mode: 'import_story', durationSec: 30,
    story: '雨夜，林青推门走进便利店。店员陈明转身，接过雨伞。两人走到街边，撑起伞，一起离开。' })
  const pid = project.project.id
  const base = `/api/projects/${pid}`
  const token = await api('POST', '/api/auth/magic-link', { email: 'flow@verification.invalid' })
  userId = (await api('POST', '/api/auth/verify', { token: token.token })).userId
  await api('POST', base + '/claim')
  const automatic = await api('POST', '/api/projects', { inputType: 'story', mode: 'automatic', durationSec: 30,
    story: '雨夜，陌生店员帮助女孩撑伞赶车。' })
  const storyBase = `/api/projects/${automatic.project.id}`
  await api('POST', storyBase + '/claim')
  const storyResult = await api('POST', storyBase + '/story')
  expect(storyResult.storyText.length).toBeGreaterThanOrEqual(300)
  expect((await api('GET', storyBase)).project.generatedStoryText).toBe(storyResult.storyText)
  expect((await status()).textCalls).toBe(1)
  const snapshot = () => api('GET', base)
  const cards = () => api('GET', base + '/characters')
  const nav = async (name: string) => page.getByRole('button', { name, exact: true }).click()
  await page.route('**/*', route => {
    const url = route.request().url()
    return url.startsWith(origin + '/') || url.startsWith('data:') || url.startsWith('blob:')
      ? route.continue() : route.abort('blockedbyclient')
  })
  await page.addInitScript(({ pid, userId }) => {
    localStorage.setItem('comicflow-project-id', pid)
    localStorage.setItem('comicflow-user-id', userId)
  }, { pid, userId })
  await page.goto('/')
  await nav('剧本')
  await page.getByRole('button', { name: '拆分为剧本', exact: true }).click()
  await page.getByRole('button', { name: '确认并进入剧本编辑器' }).first().click()
  await expect(page.getByLabel('剧本标题')).toHaveValue('隔离验证：雨夜便利店')
  expect((await status()).textCalls).toBe(2)
  const script = (await snapshot()).script
  expect(script.shots).toHaveLength(6)
  expect(script.planningExecution.skill).toBeTruthy()
  await nav('角色')
  for (const name of ['林青', '陈明']) {
    await page.getByRole('button', { name: new RegExp(`^${name}.*个镜头$`) }).click()
    await page.getByLabel('角色-appearance', { exact: true }).fill(`${name}，年轻，黑色短发，五官清晰`)
    await page.getByLabel('角色-clothing', { exact: true }).fill(name === '林青' ? '蓝色外套' : '白色衬衣')
    await page.getByLabel('角色-personality', { exact: true }).fill('沉静')
    await page.getByText('单张主图提示词（选填）', { exact: true }).click()
    await page.getByLabel('角色参考图提示词', { exact: true }).fill(`${name}，全身正面，纯白背景，清晰五官和衣料`)
    await page.getByRole('button', { name: '保存角色设定', exact: true }).click()
    await expect(page.getByText('已保存', { exact: true })).toBeVisible()
  }
  await nav('剧本')
  await page.getByRole('button', { name: '确认剧本并生成分镜' }).click()
  await expect.poll(async () => (await snapshot()).project.stage).toBe('storyboard-ready')
  expect((await status()).images).toBe(0)
  await nav('剧本')
  for (const name of ['便利店内', '店外街道']) {
    await page.locator('.asset-list').getByRole('button', { name: new RegExp(name) }).click()
    await page.getByRole('button', { name: '准备场景参考图（图片 API，可能计费）' }).click()
    await expect.poll(async () => (await snapshot()).script.scenes.find((s: any) => s.title === name)?.backgroundImageMediaType).toBe('image')
  }
  await nav('角色')
  for (const name of ['林青', '陈明']) {
    await page.getByRole('button', { name: new RegExp(`^${name}.*个镜头$`) }).click()
    if (name === '林青') {
      await page.getByLabel('图片生成方式').selectOption('candidate')
      await page.getByRole('button', { name: '生成图片', exact: true }).click()
      await expect(page.getByRole('button', { name: '确定使用这张图', exact: true })).toBeEnabled()
      expect((await cards()).find((c: any) => c.name === name).referenceImageObjectKey).toBeFalsy()
      await page.getByRole('button', { name: '确定使用这张图', exact: true }).click()
    }
    await page.getByLabel('图片生成方式').selectOption(name === '林青' ? 'board' : 'text-board')
    await page.getByRole('button', { name: '生成图片', exact: true }).click()
    await expect(page.getByRole('button', { name: '确定使用这张参考板', exact: true })).toBeEnabled()
    const card = (await cards()).find((c: any) => c.name === name)
    expect(card.referenceBoard).toBeFalsy()
    expect(card.referenceBoardCandidate).toBeTruthy()
    await page.getByRole('button', { name: '确定使用这张参考板', exact: true }).click()
    await expect(page.getByLabel('已确认角色参考板').getByRole('img')).toBeVisible()
  }
  await page.screenshot({ path: info.outputPath('confirmed-board.png'), fullPage: true })
  expect((await status()).images).toBe(5)
  const approvedCards = await cards()
  const hash = (bytes: Buffer) => createHash('sha256').update(bytes).digest('hex')
  const boardHashes = await Promise.all(approvedCards.map(async (c: any) => hash(await (await request.get(c.referenceBoard.url)).body())))
  const generatedImages = (await status()).imageRequests
  const editSources = generatedImages.filter((r: any) => r.model === 'wan2.6-image').map((r: any) =>
    hash(Buffer.from(r.input.messages[0].content.find((c: any) => c.image).image.split(',')[1], 'base64')))
  expect(editSources).toHaveLength(1)
  expect(approvedCards.find((c: any) => c.name === '陈明').referenceImageObjectKey).toBeFalsy()
  for (const card of approvedCards.filter((c: any) => c.name === '林青')) {
    expect(editSources).toContain(hash(await (await request.get(card.referenceImageUrl)).body()))
  }
  const scenes = (await snapshot()).script.scenes
  const sceneHashes: Record<string, string> = {}
  for (const scene of scenes) sceneHashes[scene.id] = hash(await (await request.get(scene.backgroundImageUrl)).body())
  const preflights: any[] = []
  await nav('画面')
  for (let i = 0; i < script.shots.length; i++) {
    const shot = script.shots[i]
    await page.getByRole('button', { name: new RegExp(`^0${i + 1} ${shot.title}`) }).click()
    const preflight = await api('POST', base + `/shots/${shot.id}/visual/preflight`, { expectedVersion: (await snapshot()).project.version })
    expect(preflight.ready, JSON.stringify(preflight)).toBe(true)
    preflights.push(preflight)
    const submitted = page.waitForResponse(r => r.url().endsWith(`/shots/${shot.id}/video-jobs`) && r.request().method() === 'POST')
    await page.getByRole('button', { name: '生成当前镜头', exact: true }).click()
    const submitResponse = await submitted
    expect(submitResponse.status()).toBe(202)
    // Replay the same operation: the API must return the same job without a new supplier call.
    const queued = await submitResponse.json()
    const repeat = await api('POST', base + `/shots/${shot.id}/video-jobs`, submitResponse.request().postDataJSON())
    expect(repeat.id).toBe(queued.id)
    if (i === 2) await page.getByRole('button', { name: '继续查询 / 保存已有任务', exact: true }).click()
    await expect(page.getByRole('button', { name: '采用此候选视频', exact: true })).toBeEnabled()
    const before = await snapshot()
    expect(before.visualAssets.find((a: any) => a.shotId === shot.id && a.valid)).toBeUndefined()
    if (i === 5) {
      const gate = await request.post(base + '/composition', { headers: { 'x-user-id': userId },
        data: { expectedVersion: before.project.version, idempotencyKey: 'not-adopted' } })
      expect(gate.ok()).toBe(false)
      expect(await gate.json()).toMatchObject({ error: 'ASSETS_INCOMPLETE', missingVisualShotIds: ['s6'] })
    }
    const recorded = (await status()).videoRequests[i]
    expect(recorded.resolution).toBe('768P')
    expect(recorded.duration).toBe(5)
    expect(recorded.content[0].text).toBe(preflight.prompt.text)
    const imageHashes = recorded.content.filter((c: any) => c.type === 'image_url')
      .map((c: any) => hash(Buffer.from(c.image_url.url.split(',')[1], 'base64')))
    for (const name of shot.characters) {
      const index = approvedCards.findIndex((c: any) => c.name === name)
      expect(index).toBeGreaterThanOrEqual(0)
      expect(imageHashes).toContain(boardHashes[index])
    }
    const tails = preflight.references.filter((r: any) => r.view === 'continuity-anchor')
    expect(tails).toHaveLength(i === 0 || i === 3 ? 0 : 1)
    expect(preflight.references.filter((r: any) => r.view === 'scene-anchor')).toHaveLength(1)
    expect(preflight.references.filter((r: any) => r.view === 'reference-board')).toHaveLength(shot.characters.length)
    expect(imageHashes).toHaveLength(shot.characters.length + 1 + tails.length)
    expect(imageHashes).toContain(sceneHashes[shot.sceneId])
    if (tails.length) {
      const previous = before.visualAssets.find((a: any) => a.shotId === script.shots[i - 1].id && a.valid)
      expect(tails[0].id).toBe(previous.shotId)
      expect(tails[0].sourceId).toBe(hash(Buffer.from(JSON.stringify(previous.lastFrameObjectKey))).slice(0, 16))
    }
    await page.getByRole('button', { name: '采用此候选视频', exact: true }).click()
    await expect.poll(async () => (await snapshot()).visualAssets.filter((a: any) => a.valid).length).toBe(i + 1)
  }
  await page.screenshot({ path: info.outputPath('six-adopted-shots.png'), fullPage: true })
  await nav('声音')
  await expect(page.getByText(/视频原声/).first()).toBeVisible()
  expect((await snapshot()).audioAssets).toHaveLength(0)
  const native = await api('POST', base + '/shots/s1/audio', { expectedVersion: (await snapshot()).project.version })
  expect(native.asset.source).toBe('video-native')
  expect(native.reused).toBe(false)
  expect(native.lipSync).toBeNull()
  const reused = await api('POST', base + '/shots/s1/audio', { expectedVersion: (await snapshot()).project.version })
  expect(reused.reused).toBe(true)
  expect(reused.asset.id).toBe(native.asset.id)
  expect((await snapshot()).lipSyncAssets).toHaveLength(0)
  // Extraction updates the timeline and invalidates any old export; compose afterwards.
  await page.reload()
  await nav('导出')
  await page.getByRole('button', { name: '开始合成', exact: true }).click()
  await expect(page.getByText('导出包已就绪', { exact: true })).toBeVisible({ timeout: 150000 })
  await page.getByRole('button', { name: '加载成片预览' }).click()
  const video = page.getByLabel('合成视频预览')
  await expect.poll(() => video.evaluate((v: HTMLVideoElement) => v.readyState)).toBeGreaterThanOrEqual(2)
  await video.evaluate(async (v: HTMLVideoElement) => { v.muted = true; await v.play() })
  await expect.poll(() => video.evaluate((v: HTMLVideoElement) => v.currentTime)).toBeGreaterThan(.2)
  await video.evaluate((v: HTMLVideoElement) => v.pause())
  const manifest = await api('GET', base + '/export')
  for (const filename of ['video.mp4', 'cover.jpg', 'subtitles.srt']) {
    const response = await request.get(manifest.downloads[filename], { headers: { 'x-user-id': userId } })
    expect(response.ok(), await response.text()).toBeTruthy()
    writeFileSync(path.join(out, filename), await response.body())
  }
  await page.screenshot({ path: info.outputPath('export-preview.png'), fullPage: true })
  await api('POST', '/test-control/restart')
  await expect.poll(async () => { const s = await status(); return s.ready && s.restarts === 1 }).toBe(true)
  await page.reload()
  await nav('导出')
  await expect(page.getByText('导出包已就绪', { exact: true })).toBeVisible()
  expect((await api('GET', '/api/model-registry')).bindings).toEqual(bindings)
  expect((await cards()).every((c: any) => c.referenceBoard?.status === 'approved')).toBe(true)
  const final = await snapshot()
  expect(final.visualAssets.filter((a: any) => a.valid)).toHaveLength(6)
  expect(final.audioAssets).toHaveLength(1)
  expect(final.audioAssets[0].id).toBe(native.asset.id)
  expect((await api('GET', storyBase)).project.generatedStoryText).toBe(storyResult.storyText)
  const resources = await api('GET', base + '/video-resources')
  expect(resources.total).toBe(7)
  expect(resources.items.filter((r: any) => r.kind === 'shot')).toHaveLength(6)
  for (const item of resources.items) {
    const access = await api('GET', base + `/video-resources/${encodeURIComponent(item.id)}/access?download=true`)
    const media = await request.get(access.url)
    expect(media.ok()).toBe(true)
    expect((await media.body()).length).toBeGreaterThan(1000)
  }
  const counts = await status()
  expect(counts).toMatchObject({ images: 5, videos: 6, textCalls: 2, failedDownload: true, realModelCalls: 0 })
  // Store compact evidence, excluding bulky base64 image payloads.
  writeFileSync(path.join(out, 'browser-report.json'), JSON.stringify({ status: 'passed', projectId: pid,
    realModelCalls: 0, textCalls: counts.textCalls, images: counts.images, videos: counts.videos,
    recoveryWithoutResubmission: true, restarts: counts.restarts,
    automaticStoryPersisted: true, textBoardWithoutMainImage: true, nativeAudioExtractedAndReused: true,
    videoResourcesReadableAfterRestart: resources.total,
    preflights: preflights.map(p => ({ references: p.references, parameters: p.parameters })),
    exportManifest: manifest, boardHashes }, null, 2))
})
