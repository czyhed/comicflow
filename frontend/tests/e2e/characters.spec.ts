import { expect, test } from '@playwright/test'
import type { CharacterCard } from '../../src/types'

test('opening characters explains a recorded unknown job without raw errors or resubmission', async ({ page }) => {
  const writes: string[] = []
  const card = { id: 'c1', name: '小雨', appearance: '短发', clothing: '蓝外套', personality: '沉静', voice: { language: 'zh-CN' }, referenceImageUrl: 'https://offline.invalid/main.png', referenceImageMediaType: 'image' }
  await page.route('https://offline.invalid/**', route => route.fulfill({ status: 204 }))
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname
    if (route.request().method() !== 'GET') writes.push(path)
    if (path.endsWith('/image-jobs')) return route.fulfill({ json: { items: [{
      id: 'ijob-existing', characterId: 'c1', purpose: 'board', status: 'unknown',
      error: 'PROVIDER_UNAVAILABLE', taskId: null, callsStarted: 1, completedSteps: [], canRecover: false,
      createdAt: '2026-09-21T08:41:36+00:00', updatedAt: '2026-09-21T08:41:40+00:00',
      errorDetail: { stage: 'submitting', transportError: 'ReadError' },
    }] } })
    if (path.endsWith('/characters')) return route.fulfill({ json: [card] })
    if (path === '/api/projects/unknown-board') return route.fulfill({ json: {
      project: { id: 'unknown-board', version: 3, stage: 'storyboard-ready', input: { mode: 'import_story' } },
      script: { title: '雨夜', scenes: [], shots: [] }, jobs: [], visualAssets: [], audioAssets: [], timelines: {},
    } })
    return route.fulfill({ json: {} })
  })
  await page.addInitScript(() => localStorage.setItem('comicflow-project-id', 'unknown-board'))
  await page.goto('/')
  await page.getByRole('button', { name: '角色', exact: true }).click()
  const progress = page.getByRole('region', { name: '图片生成进度' })
  await expect(progress.getByText('作业详情', { exact: true })).toBeVisible()
  await expect(progress).toContainText('本地执行已停止，不会继续等待出图')
  await expect(progress).toContainText('模型服务请求失败或暂时不可用')
  await expect(page.getByText('错误代码：PROVIDER_UNAVAILABLE', { exact: true })).not.toBeVisible()
  await expect(page.getByLabel('图片生成方式')).toBeDisabled()
  await expect(page.getByRole('button', { name: '生成图片', exact: true })).toBeDisabled()
  await expect(page.getByRole('button', { name: '恢复已有图片作业' })).toHaveCount(0)
  await progress.getByText('作业详情', { exact: true }).click()
  await progress.getByText('查看错误详情', { exact: true }).click()
  await expect(progress).toContainText('ReadError')
  await expect(progress).toContainText('ijob-existing')
  await page.reload()
  await page.getByRole('button', { name: '角色', exact: true }).click()
  await expect(page.getByRole('region', { name: '图片生成进度' })).toContainText('本地执行已停止')
  expect(writes).toEqual([])
})

test('text board needs no main image and is adopted only after explicit confirmation', async ({ page }, info) => {
  let version = 3
  let submissions = 0
  let approvals = 0
  const card: CharacterCard = { id: 'c1', name: '小雨', appearance: '黑色短发', clothing: '蓝色外套', personality: '沉静', voice: { language: 'zh-CN' } }
  const jobs: object[] = []
  await page.route('https://offline.invalid/**', route => route.fulfill({ status: 204 }))
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname
    const method = route.request().method()
    if (path.endsWith('/image-jobs') && method === 'POST') {
      expect(route.request().postDataJSON()).toMatchObject({ purpose: 'text-board', expectedVersion: version })
      expect(card.referenceImageUrl).toBeUndefined()
      submissions++
      card.referenceBoardCandidate = { id: 'text-board', url: 'https://offline.invalid/board.png', mediaType: 'image', status: 'candidate', generationMode: 'single-text-board' }
      version++
      const job = { id: 'ijob-text', characterId: 'c1', purpose: 'text-board', status: 'succeeded', callsStarted: 1, completedSteps: ['board-candidate'], applied: true, canRecover: false, createdAt: '2026-09-21T10:00:00Z', updatedAt: '2026-09-21T10:00:01Z' }
      jobs.push(job)
      return route.fulfill({ status: 202, json: job })
    }
    if (path.endsWith('/image-jobs')) return route.fulfill({ json: { items: jobs } })
    if (path.endsWith('/reference-board/approve') && method === 'POST') {
      expect(route.request().postDataJSON()).toEqual({ candidateId: 'text-board', expectedVersion: version })
      approvals++
      card.referenceBoard = { ...card.referenceBoardCandidate!, status: 'approved' }
      card.referenceBoardCandidate = null
      version++
      return route.fulfill({ json: { character: card, projectVersion: version } })
    }
    expect(method).toBe('GET')
    if (path.endsWith('/characters')) return route.fulfill({ json: [card] })
    if (path === '/api/projects/text-board') return route.fulfill({ json: {
      project: { id: 'text-board', version, stage: 'storyboard-ready', input: { mode: 'import_story' } },
      script: { title: '雨夜', scenes: [], shots: [] }, jobs: [], visualAssets: [], audioAssets: [], timelines: {},
    } })
    return route.fulfill({ json: {} })
  })
  await page.addInitScript(() => localStorage.setItem('comicflow-project-id', 'text-board'))
  await page.goto('/')
  await page.getByRole('button', { name: '角色', exact: true }).click()
  const generate = page.getByRole('button', { name: '生成图片', exact: true })
  await expect(page.getByLabel('图片生成方式')).toHaveValue('text-board')
  await expect(page.getByLabel('图片生成方式').locator('option[value=board]')).toHaveAttribute('disabled', '')
  await page.getByText('输入与模型说明', { exact: true }).click()
  await expect(page.getByLabel('角色参考图生成')).toContainText('此项目未设置统一画风')
  await expect(generate).toBeEnabled()
  await page.getByLabel('角色-clothing').fill('未保存的新服装')
  await expect(generate).toBeDisabled()
  await page.getByLabel('角色-clothing').fill('蓝色外套')
  expect(submissions).toBe(0)
  await generate.click()
  await expect(page.getByLabel('候选角色参考板')).toContainText('脸部特写')
  await expect(page.getByLabel('已确认角色参考板')).toHaveCount(0)
  await page.reload()
  await page.getByRole('button', { name: '角色', exact: true }).click()
  await expect(generate).toBeEnabled()
  await expect(page.getByLabel('图片生成方式')).toHaveValue('text-board')
  expect(submissions).toBe(1)
  expect(approvals).toBe(0)
  await page.getByRole('button', { name: '确定使用这张参考板' }).click()
  await expect(page.getByLabel('已确认角色参考板')).toBeVisible()
  await expect(page.getByText('已确认角色设定板', { exact: true })).toBeVisible()
  await expect(page.getByLabel('候选角色参考板')).toHaveCount(0)
  await page.reload()
  await page.getByRole('button', { name: '角色', exact: true }).click()
  await expect(page.getByLabel('已确认角色参考板')).toBeVisible()
  await page.setViewportSize({ width: 390, height: 844 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.getByLabel('角色参考图生成').screenshot({ path: info.outputPath('text-board-entry.png') })
  expect(submissions).toBe(1)
  expect(approvals).toBe(1)
})

test('reference review and views remain explicit and survive reload and character switching', async ({ page }, info) => {
  let version = 3
  const imageJobs: object[] = []
  const writes: string[] = []
  const cards: CharacterCard[] = ['小雨', '小林'].map((name, i) => ({ id: `c${i + 1}`, name,
    appearance: '黑色短发', clothing: '蓝色外套', personality: '沉稳',
    referenceImagePrompt: '单人全身，纯色背景', voice: { language: 'zh-CN' }, revision: 0 }))
  const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLbtAAAAABJRU5ErkJggg==', 'base64')
  await page.route('https://offline.invalid/**', route => route.fulfill({ contentType: 'image/png', body: png }))
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname
    const card = cards[0]
    if (route.request().method() !== 'GET') {
      writes.push(path)
      expect(route.request().postDataJSON().expectedVersion).toBe(version)
    }
    if (path.endsWith('/image-jobs') && route.request().method() === 'GET') return route.fulfill({ json: { items: imageJobs } })
    const purpose = path.endsWith('/image-jobs') ? route.request().postDataJSON().purpose : null
    const finish = () => {
      const job = { id: `image-job-${version}`, characterId: 'c1', purpose, status: 'succeeded', createdAt: String(version), updatedAt: String(version), completedSteps: [purpose === 'board' ? 'board-candidate' : purpose], callsStarted: 1, applied: true, canRecover: false }
      imageJobs.push(job)
      return route.fulfill({ status: 202, json: job })
    }
    if (purpose === 'candidate') {
      card.referenceImageCandidate = { id: 'candidate-1', url: 'https://offline.invalid/main.png', mediaType: 'image', status: 'candidate' }
      version++
      return finish()
    }
    if (path.endsWith('/reference-candidate/approve')) {
      expect(route.request().postDataJSON().candidateId).toBe('candidate-1')
      card.referenceImageUrl = card.referenceImageCandidate!.url
      card.referenceImageMediaType = 'image'
      card.referenceImageCandidate = null
      card.referenceImageStatus = 'approved'
      version++
      return route.fulfill({ json: { character: card, projectVersion: version } })
    }
    if (purpose === 'board') {
      card.referenceBoard = { id: 'old', url: 'https://offline.invalid/old.png', status: 'approved' }
      card.referenceBoardCandidate = { id: 'board-candidate', url: 'https://offline.invalid/board.png', mediaType: 'image', status: 'candidate' }
      version++
      return finish()
    }
    if (path.endsWith('/reference-board/approve')) {
      expect(route.request().postDataJSON().candidateId).toBe('board-candidate')
      card.referenceBoard = { ...card.referenceBoardCandidate!, status: 'approved' }
      card.referenceBoardCandidate = null
      version++
      return route.fulfill({ json: { character: card, projectVersion: version } })
    }
    if (path.endsWith('/characters')) return route.fulfill({ json: cards })
    if (path === '/api/projects/reference-project') return route.fulfill({ json: {
      project: { id: 'reference-project', stage: 'storyboard-ready', version, input: { mode: 'import_script' } },
      script: { title: '雨夜', scenes: [], shots: [] }, jobs: [], creditLedger: [],
      visualAssets: [], audioAssets: [], lipSyncAssets: [], timelines: {},
    } })
    return route.fulfill({ json: {} })
  })
  await page.addInitScript(() => localStorage.setItem('comicflow-project-id', 'reference-project'))
  await page.goto('/')
  await page.getByRole('button', { name: '角色', exact: true }).click()
  await page.getByLabel('图片生成方式').selectOption('candidate')
  await page.getByRole('button', { name: '生成图片', exact: true }).click()
  await expect(page.getByLabel('角色候选参考图')).toBeVisible()
  expect(writes).toHaveLength(1)
  await page.reload()
  await page.getByRole('button', { name: '角色', exact: true }).click()
  await expect(page.getByRole('img', { name: '小雨候选参考图' })).toBeVisible()
  await expect(page.getByLabel('图片生成方式').locator('option[value=board]')).toHaveAttribute('disabled', '')
  await page.getByLabel('角色-clothing').fill('未保存的新服装')
  await expect(page.getByRole('button', { name: '确定使用这张图', exact: true })).toBeDisabled()
  expect(writes).toHaveLength(1)
  await page.getByLabel('角色-clothing').fill('蓝色外套')
  await page.getByRole('button', { name: '确定使用这张图' }).click()
  await expect(page.getByRole('img', { name: '小雨已确认参考图' })).toBeVisible()
  expect(writes).toHaveLength(2)
  await page.getByLabel('图片生成方式').selectOption('board')
  await page.getByRole('button', { name: '生成图片', exact: true }).click()
  await expect(page.getByLabel('候选角色参考板')).toBeVisible()
  await expect(page.getByRole('img', { name: '小雨已确认参考板' })).not.toBeVisible()
  await page.getByText('查看当前已确认参考板', { exact: true }).click()
  await expect(page.getByRole('img', { name: '小雨已确认参考板' })).toHaveAttribute('src', 'https://offline.invalid/old.png')
  expect(writes).toHaveLength(3)
  await page.reload()
  await page.getByRole('button', { name: '角色', exact: true }).click()
  await expect(page.getByLabel('候选角色参考板')).toBeVisible()
  await page.getByLabel('候选角色参考板').screenshot({ path: info.outputPath('board-candidate.png') })
  expect(writes).toHaveLength(3)
  await page.getByRole('button', { name: '确定使用这张参考板' }).click()
  await expect(page.getByLabel('候选角色参考板')).toHaveCount(0)
  await expect(page.getByRole('img', { name: '小雨已确认参考板' })).toHaveAttribute('src', 'https://offline.invalid/board.png')
  expect(writes).toHaveLength(4)
  await page.getByLabel('角色-clothing').fill('未保存的服装')
  await page.getByRole('button', { name: '小林 0 个镜头' }).click()
  await expect(page.getByLabel('角色-name')).toHaveValue('小林')
  await expect(page.getByLabel('已确认角色参考板')).toHaveCount(0)
  await page.getByRole('button', { name: '小雨 0 个镜头' }).click()
  await expect(page.getByLabel('角色-clothing')).toHaveValue('蓝色外套')
  await expect(page.getByLabel('已确认角色参考板').getByRole('img')).toHaveCount(1)
  await page.setViewportSize({ width: 390, height: 844 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.screenshot({ path: info.outputPath('character-references.png'), fullPage: true })
  expect(writes).toHaveLength(4)
  // Reload an invalidated reference: viewing the old file must never submit generation.
  cards[0].referenceBoard = { status: 'stale', url: 'https://offline.invalid/old-board.jpg' }
  cards[0].referenceViews = []
  await page.reload()
  await page.getByRole('button', { name: '角色', exact: true }).click()
  await expect(page.getByLabel('已失效角色参考板')).toContainText('不会用于新视频')
  await page.getByText('查看旧参考板', { exact: true }).click()
  await expect(page.getByRole('img', { name: '小雨已失效参考板' })).toBeVisible()
  await page.getByLabel('图片生成方式').selectOption('board')
  await expect(page.getByRole('button', { name: '生成图片', exact: true })).toBeEnabled()
  expect(writes).toHaveLength(4)
})

test('purpose scoped character drafts preserve other fields and never generate media', async ({ page }) => {
  let card = { id: 'c1', name: '小雨', appearance: '手填短发', clothing: '', personality: '', voice: { language: 'zh-CN' }, referenceImagePrompt: '原图片提示词', revision: 0 }
  let calls = 0
  const unexpectedWrites: string[] = []
  const snapshot = { project: { id: 'prompt-project', stage: 'awaiting-confirmation', version: 3 }, script: { title: '雨夜', scenes: [], shots: [] }, jobs: [], creditLedger: [], visualAssets: [], audioAssets: [], lipSyncAssets: [], timelines: {} }
  await page.route('**/api/**', route => {
    if (route.request().method() !== 'GET') unexpectedWrites.push(route.request().url())
    return route.fulfill({ json: {} })
  })
  await page.route('**/api/projects', route => route.fulfill({ json: [snapshot] }))
  await page.route('**/api/projects/prompt-project', route => route.fulfill({ json: snapshot }))
  await page.route('**/api/projects/prompt-project/characters', route => route.fulfill({ json: [card] }))
  await page.route('**/api/projects/prompt-project/characters/prompt-preview', route => {
    calls++
    const body = route.request().postDataJSON()
    expect(body.fields.appearance).toBe('手填短发')
    expect(body.instructions).toBe('保持蓝色外套')
    if (calls <= 2) {
      expect(body.purpose).toBe('settings')
      expect(body.outputFields).toEqual(['clothing', 'personality'])
      if (calls === 1) return route.fulfill({ status: 502, json: { error: 'CHARACTER_PROMPT_INVALID' } })
      return route.fulfill({ json: { draft: { name: '小雨', clothing: '蓝色外套', personality: '沉稳' }, expectedVersion: 3, expectedRevision: 0 } })
    }
    expect(body.purpose).toBe('reference-image')
    expect(body.outputFields).toBeUndefined()
    expect(body.fields.clothing).toBe('蓝色外套')
    return route.fulfill({ json: { draft: { name: '小雨', referenceImagePrompt: '蓝色棉布外套，柔和主光，清晰五官。' }, expectedVersion: 3, expectedRevision: 1 } })
  })
  await page.route('**/api/projects/prompt-project/characters/c1', route => {
    const body = route.request().postDataJSON()
    expect(body.expectedRevision).toBe(card.revision)
    expect(body.expectedVersion).toBe(3)
    card = { ...card, ...body, revision: card.revision + 1 }
    return route.fulfill({ json: card })
  })
  await page.addInitScript(() => localStorage.setItem('comicflow-project-id', 'prompt-project'))
  await page.goto('/')
  await page.getByRole('button', { name: '角色', exact: true }).click()
  await expect(page.getByLabel('角色提示词用途')).toHaveValue('settings')
  await expect(page.getByLabel('生成设定-外观')).not.toBeChecked()
  await page.getByLabel('角色提示词补充要求').fill('保持蓝色外套')
  await page.getByRole('button', { name: '生成所选角色设定', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('未返回合格的中文角色提示词')
  await expect(page.getByLabel('角色-appearance', { exact: true })).toHaveValue('手填短发')
  await page.getByRole('button', { name: '生成所选角色设定', exact: true }).click()
  await expect(page.getByLabel('草稿-服装')).toHaveValue('蓝色外套')
  await expect(page.getByLabel('草稿-外观')).toHaveCount(0)
  await expect(page.getByLabel('草稿-参考图提示词')).toHaveCount(0)
  await page.getByRole('button', { name: '采用草稿到编辑区' }).click()
  await expect(page.getByLabel('角色-appearance', { exact: true })).toHaveValue('手填短发')
  await expect(page.getByLabel('角色参考图提示词', { exact: true })).toHaveValue('原图片提示词')
  await page.getByRole('button', { name: '保存角色设定', exact: true }).click()
  await expect(page.getByText('已保存', { exact: true })).toBeVisible()
  await page.getByLabel('角色提示词用途').selectOption('reference-image')
  await page.getByRole('button', { name: '润色主图提示词', exact: true }).click()
  await expect(page.getByLabel('草稿-参考图提示词')).toBeVisible()
  await expect(page.getByLabel('草稿-服装')).toHaveCount(0)
  await page.getByLabel('草稿-参考图提示词').fill('用户修改：漫画风格，蓝色棉布外套，清晰五官。')
  await page.screenshot({ path: test.info().outputPath('character-prompt-purpose.png'), fullPage: true })
  await page.getByRole('button', { name: '采用草稿到编辑区' }).click()
  await page.getByRole('button', { name: '保存角色设定', exact: true }).click()
  await expect(page.getByText('已保存', { exact: true })).toBeVisible()
  await page.reload()
  await page.getByRole('button', { name: '角色', exact: true }).click()
  await expect(page.getByLabel('角色参考图提示词', { exact: true })).toHaveValue(card.referenceImagePrompt)
  expect(card.appearance).toBe('手填短发')
  expect(card.personality).toBe('沉稳')
  expect(calls).toBe(3)
  expect(unexpectedWrites).toEqual([])
})

test('saved script characters can be synced edited bound and restored without generation', async ({ page }) => {
  let version = 3
  let cards: CharacterCard[] = []
  let characterIds: string[] = []
  const generated: string[] = []
  const card = { id: 'chr-xiaoyu', projectId: 'characters-project', name: '林小雨', appearance: '', clothing: '', personality: '', voice: { language: 'zh-CN' }, referenceImageUrl: 'https://assets.test/old-video.mp4' }
  const script = () => ({ title: '雨夜倒影', scenes: [{ id: 'scene-1', title: '公交车', shotIds: ['shot-1'] }], shots: [{ id: 'shot-1', order: 1, title: '登车', action: '上车', emotion: '倦怠', shotSize: '中景', durationSec: 30, visualDescription: 'rain-streaked window reflects blurred city lights', dialogue: '', narration: '雨夜，她登上公交车。', characters: ['林小雨'], characterIds }] })
  const project = () => ({ id: 'characters-project', stage: 'awaiting-confirmation', version, input: { inputType: 'story', mode: 'import_story', durationSec: 30, story: '雨夜倒影' } })
  const snapshot = () => ({ project: project(), script: script(), jobs: [], creditLedger: [], visualAssets: [], audioAssets: [], lipSyncAssets: [], timelines: {} })
  await page.route('**/api/**', route => {
    if (route.request().method() !== 'GET') generated.push(route.request().url())
    return route.fulfill({ json: {} })
  })
  await page.route('**/api/projects', route => route.fulfill({ json: [snapshot()] }))
  await page.route('**/api/projects/characters-project', route => route.fulfill({ json: snapshot() }))
  await page.route('**/api/projects/characters-project/characters', route => route.fulfill({ json: cards }))
  await page.route('**/api/projects/characters-project/characters/sync', route => {
    expect(route.request().postDataJSON().expectedVersion).toBe(version)
    cards = [card]; characterIds = [card.id]; version++
    return route.fulfill({ json: { project: project(), script: script() } })
  })
  await page.route('**/api/projects/characters-project/characters/chr-xiaoyu', route => {
    cards = [{ ...card, ...route.request().postDataJSON() }]
    return route.fulfill({ json: cards[0] })
  })
  await page.route('**/api/projects/characters-project/script/shots/shot-1/characters', route => {
    const body = route.request().postDataJSON()
    expect(body.expectedVersion).toBe(version)
    characterIds = body.characterIds; version++
    return route.fulfill({ json: { characterIds, projectVersion: version } })
  })
  await page.addInitScript(() => localStorage.setItem('comicflow-project-id', 'characters-project'))
  await page.goto('/')
  await page.locator('[aria-label="工作区导航"] button[aria-label="角色"]').click()
  await expect(page.getByText('林默', { exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: '从已保存剧本同步角色' }).click()
  await expect(page.getByLabel('角色-name')).toHaveValue('林小雨')
  await page.getByText('出场镜头与绑定', { exact: true }).click()
  await expect(page.getByRole('checkbox', { name: '登车' })).toBeChecked()
  await page.getByLabel('角色-appearance').fill('黑色短发，眼下青黑')
  await page.getByLabel('角色-clothing').fill('深色外套')
  await page.getByLabel('角色-personality').fill('沉稳')
  await page.getByRole('button', { name: '保存角色设定' }).click()
  await expect(page.getByText('已保存', { exact: true })).toBeVisible()
  await expect(page.getByRole('img', { name: '林小雨参考图' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '生成图片', exact: true })).toBeEnabled()
  await page.getByLabel('角色-clothing').fill('未保存的新服装')
  await expect(page.getByRole('button', { name: '生成图片', exact: true })).toBeDisabled()
  await page.getByRole('checkbox', { name: '登车' }).click()
  await expect(page.getByRole('checkbox', { name: '登车' })).not.toBeChecked()
  await page.reload()
  await page.locator('[aria-label="工作区导航"] button[aria-label="角色"]').click()
  await expect(page.getByLabel('角色-appearance')).toHaveValue('黑色短发，眼下青黑')
  await page.locator('[aria-label="工作区导航"] button[aria-label="剧本"]').click()
  await expect(page.getByText('此镜头保留了旧版英文描述', { exact: false })).toBeVisible()
  await expect(page.getByLabel('cameraMovement-shot-1')).toBeVisible()
  expect(generated).toEqual([])
})
