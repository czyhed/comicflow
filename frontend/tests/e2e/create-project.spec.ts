import { textStreamServer } from '../helpers/text-stream-server'
import { expect, test } from '@playwright/test'

test.beforeEach(async ({ page }) => {
  // Unmocked polling/style requests must never reach a developer's running API.
  await page.route('**/api/**', route => route.abort('blockedbyclient'))
})

test('creator can generate a script and enter the script workspace', async ({ page }) => {
  await page.route('**/api/**', route => route.abort('blockedbyclient'))
  await page.route('**/api/model-registry', route => route.fulfill({ json: {
    revision: 0, scope: 'postgresql', connections: [], models: [], bindings: {},
    usages: {}, templates: {},
  } }))
  const splitScript = { title: '雨夜', scenes: [], shots: [] }
  let previewGenerations = 0
  let commits = 0
  await page.route('**/api/projects', (route) => route.fulfill({
    json: { project: { id: 'prj_e2e', stage: 'story', version: 1 }, guestSession: { id: 'gst_e2e', projectId: 'prj_e2e' } },
  }))
  await page.route('**/api/projects/prj_e2e/story', (route) => route.fulfill({
    json: { project: { id: 'prj_e2e', stage: 'story-generated', version: 2, generatedStoryText: '雨夜故事文本。' }, storyText: '雨夜故事文本。' },
  }))
  await page.route('**/api/projects/prj_e2e/script/preview', async (route) => {
    if (route.request().method() === 'POST') previewGenerations += 1
    if (route.request().method() === 'PUT') {
      commits += 1
      await route.fulfill({ json: { project: { id: 'prj_e2e', stage: 'awaiting-confirmation', version: 3 }, script: splitScript } })
      return
    }
    await route.fulfill({ json: { script: splitScript, summary: { scenes: 0, shots: 0, dialogue: 0, narration: 0, issues: [] }, expectedVersion: 2 } })
  })
  await page.route('**/api/projects/prj_e2e', (route) => route.fulfill({
    json: { project: { id: 'prj_e2e', stage: 'story-generated', version: 2, generatedStoryText: '雨夜故事文本。' }, jobs: [], script: null },
  }))

  await page.goto('/')
  await page.getByRole('button', { name: '模型 API' }).click()
  await expect(page.getByRole('dialog', { name: '模型管理', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '连接与密钥', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '用途选择', exact: true })).toBeVisible()
  await page.getByRole('button', { name: '关闭模型管理' }).click()
  await page.getByText('全自动').click()
  await page.getByRole('button', { name: '生成故事文本' }).click()
  await expect(page.getByRole('button', { name: '进入剧本模块拆分' })).toBeVisible()
  await page.getByRole('button', { name: '进入剧本模块拆分' }).click()
  await page.getByRole('button', { name: '拆分为剧本' }).click()
  await expect(page.getByRole('region', { name: '剧本拆分预览' })).toBeVisible()
  expect(previewGenerations).toBe(1)
  expect(commits).toBe(0)
  await page.getByRole('button', { name: '确认并进入剧本编辑器' }).first().click()
  await expect(page.getByText('剧本编辑器', { exact: true })).toBeVisible()
  expect(commits).toBe(1)
  await expect(page.getByRole('button', { name: '资产管理' })).toHaveCount(0)
  await expect(page.getByRole('checkbox', { name: '我收藏的' })).toHaveCount(0)
})

test('creation modes keep separate bounds on a narrow viewport', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/')

  const modes = page.locator('.mode-row > label')
  await expect(modes).toHaveCount(2)

  const bounds = await modes.evaluateAll((elements) => elements.map((element) => {
    const rect = element.getBoundingClientRect()
    return { top: rect.top, bottom: rect.bottom, left: rect.left, right: rect.right, height: rect.height }
  }))

  expect(bounds.every((item) => item.height >= 52)).toBe(true)
  expect(bounds[0].bottom).toBeLessThanOrEqual(bounds[1].top)
})

test('creation page presents one import entry for existing story or script', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByText('导入内容并整理')).toBeVisible()
  await expect(page.getByText('我的故事')).toHaveCount(0)
  await expect(page.getByText('我的剧本')).toHaveCount(0)
})

test('import content previews script before writing it', async ({ page }) => {
  let previewCalls = 0
  let commitCalls = 0
  await page.route('**/api/projects', (route) => route.fulfill({ json: { project: { id: 'prj_preview', stage: 'story', version: 1 }, guestSession: { id: 'gst_preview', projectId: 'prj_preview' } } }))
  await page.route('**/api/projects/prj_preview/script/preview', (route) => {
    if (route.request().method() === 'POST') previewCalls += 1
    if (route.request().method() === 'PUT') commitCalls += 1
    return route.fulfill({ json: { project: { id: 'prj_preview', stage: 'script-completed', version: 2 }, script: { title: '预览剧本', scenes: [{ id: 's1', title: '场景', shotIds: ['shot-1'] }], shots: [{ id: 'shot-1', sceneId: 's1', order: 1, title: '镜头', action: '固定', emotion: '平静', shotSize: '中景', durationSec: 30, visualDescription: '车站', dialogue: '你来了。', narration: '' }] }, summary: { scenes: 1, shots: 1, dialogue: 1, narration: 0, issues: [] }, expectedVersion: 1 } })
  })
  await page.goto('/')
  await page.getByText('导入内容并整理').click()
  await page.getByRole('button', { name: '拆分为剧本' }).click()
  await expect(page.getByText('预览剧本', { exact: true })).toBeVisible()
  await expect(page.getByText('1 条', { exact: false })).toBeVisible()
  expect(previewCalls).toBe(1)
  expect(commitCalls).toBe(0)
  await page.getByRole('button', { name: '确认并进入剧本编辑器' }).first().click()
  await expect.poll(() => commitCalls).toBe(1)
})

test('script editor shows all shots assigned to the selected scene', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('comicflow-project-id', 'prj_three_shots'))
  await page.route('**/api/projects/prj_three_shots', (route) => route.fulfill({ json: {
    project: { id: 'prj_three_shots', stage: 'script-completed', version: 2 },
    script: { title: '三镜头', scenes: [{ id: 'scene-1', title: '车站', shotIds: ['shot-1'] }], shots: [
      { id: 'shot-1', sceneId: 'scene-1', order: 1, title: '镜头一', action: '固定', emotion: '平静', shotSize: '中景', durationSec: 10, visualDescription: '车站', dialogue: '一', narration: '' },
      { id: 'shot-2', sceneId: 'scene-1', order: 2, title: '镜头二', action: '推近', emotion: '紧张', shotSize: '近景', durationSec: 10, visualDescription: '车门', dialogue: '二', narration: '' },
      { id: 'shot-3', sceneId: 'scene-1', order: 3, title: '镜头三', action: '回头', emotion: '惊讶', shotSize: '特写', durationSec: 10, visualDescription: '姐姐', dialogue: '三', narration: '' },
    ] }, jobs: [], visualAssets: [], audioAssets: [], lipSyncAssets: [], creditLedger: [],
  } }))
  await page.goto('/')
  await page.locator('[aria-label="工作区导航"] button[aria-label="剧本"]').click()
  await expect(page.getByLabel('镜头标题-shot-1')).toBeVisible()
  await expect(page.getByLabel('镜头标题-shot-2')).toBeVisible()
  await expect(page.getByLabel('镜头标题-shot-3')).toBeVisible()
})

test('legacy incomplete scripts show issues and offer resplitting', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('comicflow-project-id', 'prj_legacy_incomplete'))
  await page.route('**/api/projects/prj_legacy_incomplete', (route) => route.fulfill({ json: {
    project: { id: 'prj_legacy_incomplete', stage: 'script-completed', version: 2, generatedStoryText: '故事文本' },
    script: { title: '旧剧本', scenes: [{ id: 'scene-1', title: '旧场景', shotIds: ['shot-1'] }], shots: [{ id: 'shot-1', order: 1, title: '旧镜头', action: '固定', emotion: '平静', shotSize: '中景', durationSec: 30, visualDescription: '画面', dialogue: '', narration: '' }] },
    jobs: [], visualAssets: [], audioAssets: [], lipSyncAssets: [], creditLedger: [],
  } }))
  await page.goto('/')
  await page.locator('[aria-label="工作区导航"] button[aria-label="剧本"]').click()
  await expect(page.getByText('剧本需要重新拆分')).toBeVisible()
  await expect(page.getByText('镜头数量不足')).toBeVisible()
  await expect(page.getByRole('button', { name: '重新拆分剧本' })).toBeVisible()
})

test('creator can read the generated script beside the creation controls', async ({ page }) => {
  const script = {
    title: '雨夜末班车',
    scenes: [{ id: 'scene-1', title: '车站', shotIds: ['shot-1'] }],
    shots: [{
      id: 'shot-1', order: 1, title: '姐姐回头', action: '缓慢回头', emotion: '惊讶',
      shotSize: '特写', durationSec: 30, visualDescription: '姐姐在最后一排回头',
      dialogue: '你终于来了。', narration: '',
    }],
  }
  await page.route('**/api/projects', (route) => route.fulfill({
    json: { project: { id: 'prj_side_preview', stage: 'story', version: 1 }, guestSession: { id: 'gst_side_preview', projectId: 'prj_side_preview' } },
  }))
  await page.route('**/api/projects/prj_side_preview/story', (route) => route.fulfill({
    json: { project: { id: 'prj_side_preview', stage: 'story-generated', version: 2, generatedStoryText: '姐姐在最后一排回头。' }, storyText: '姐姐在最后一排回头。' },
  }))

  await page.goto('/')
  await page.getByText('全自动').click()
  await page.getByRole('button', { name: '生成故事文本' }).click()
  await expect(page.getByText('姐姐在最后一排回头。')).toBeVisible()
  await expect(page.getByRole('button', { name: '进入剧本模块拆分' })).toBeVisible()
})

test('automatic creation generates editable story text before script splitting', async ({ page }) => {
  let storyRequested = false
  let savedText = ''
  await page.route('**/api/projects', (route) => route.fulfill({
    json: { project: { id: 'prj_auto_text', stage: 'story', version: 1, input: { inputType: 'story', story: '一个足够长的故事输入', durationSec: 60, mode: 'automatic' } }, guestSession: { id: 'gst_auto_text', projectId: 'prj_auto_text' } },
  }))
  await page.route('**/api/projects/prj_auto_text/story', async (route) => {
    storyRequested = true
    if (route.request().method() === 'PATCH') {
      savedText = (route.request().postDataJSON() as { storyText: string }).storyText
      await route.fulfill({ json: { project: { id: 'prj_auto_text', stage: 'story-generated', version: 3, generatedStoryText: savedText }, storyText: savedText } })
      return
    }
    await route.fulfill({ json: { project: { id: 'prj_auto_text', stage: 'story-generated', version: 2, input: { inputType: 'story', story: '一个足够长的故事输入', durationSec: 60, mode: 'automatic' }, generatedStoryText: '这是模型生成的故事文本。' }, storyText: '这是模型生成的故事文本。' } })
  })
  await page.goto('/')
  await page.getByText('全自动').click()
  await page.getByRole('button', { name: '生成故事文本' }).click()
  await expect.poll(() => storyRequested).toBe(true)
  await expect(page.getByLabel('生成的故事文本')).toHaveValue('这是模型生成的故事文本。')
  await expect(page.getByRole('button', { name: '进入剧本模块拆分' })).toBeVisible()
  await expect(page.locator('.script-preview')).toHaveCount(0)
  await page.getByLabel('生成的故事文本').fill('这是修改后的故事文本。')
  await page.getByRole('button', { name: '保存并进入剧本模块' }).click()
  await expect.poll(() => savedText).toBe('这是修改后的故事文本。')
})

test('automatic story preview follows the persisted project mode after UI state drifts', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('comicflow-project-id', 'prj_auto_mode'))
  await page.route('**/api/projects/prj_auto_mode', (route) => route.fulfill({ json: {
    project: {
      id: 'prj_auto_mode',
      stage: 'story-generated',
      version: 2,
      input: { inputType: 'story', story: '原始故事', durationSec: 60, mode: 'automatic' },
      generatedStoryText: '刷新后恢复的自动故事文本。',
    },
    script: null,
    jobs: [],
    visualAssets: [],
    audioAssets: [],
    lipSyncAssets: [],
    creditLedger: [],
  } }))

  await page.goto('/')
  await expect(page.getByLabel('生成的故事文本')).toHaveValue('刷新后恢复的自动故事文本。')

  // A stale local radio selection must not hide a result from the persisted project.
  await page.getByText('导入内容并整理').click()
  await expect(page.getByLabel('生成的故事文本')).toBeVisible()

  // ...but the radio itself must still follow the click, because it selects the mode
  // for the NEXT project the composer creates. Deriving its checked state from the
  // loaded project instead froze it on the saved mode while the action button below
  // switched, leaving the two controls contradicting each other.
  const radios = page.locator('.mode-row input[type=radio]')
  await expect(radios.nth(0)).not.toBeChecked()
  await expect(radios.nth(1)).toBeChecked()
  await expect(page.locator('button.primary-command')).toContainText('拆分为剧本')

  await page.reload()
  await expect(page.getByLabel('生成的故事文本')).toHaveValue('刷新后恢复的自动故事文本。')
})

test('script workspace previews a split and can retry a failed preview', async ({ page }) => {
  let previewAttempts = 0
  let commits = 0
  const script = { title: '拆分后的剧本', scenes: [{ id: 'scene-1', title: '车站', shotIds: ['shot-1'] }], shots: [{ id: 'shot-1', title: '回头', action: '回头', emotion: '惊讶', shotSize: '特写', durationSec: 30, visualDescription: '姐姐回头', dialogue: '', narration: '雨声' }] }
  await page.addInitScript(() => localStorage.setItem('comicflow-project-id', 'prj_split_text'))
  await page.route('**/api/projects/prj_split_text/generation-session', route => route.fulfill({ json: {
    id: 'gen_split', projectId: 'prj_split_text', mode: 'automatic',
    stage: 'story-generated', status: 'paused', retryCount: 0,
  } }))
  await page.route('**/api/projects/prj_split_text', (route) => route.fulfill({
    json: { project: { id: 'prj_split_text', stage: 'story-generated', version: 2, input: { inputType: 'story', story: '原始故事', durationSec: 60, mode: 'automatic' }, generatedStoryText: '待拆分的故事文本。' }, script: null, jobs: [], visualAssets: [], audioAssets: [], lipSyncAssets: [], creditLedger: [] },
  }))
  await page.route('**/api/projects/prj_split_text/script/preview', async (route) => {
    if (route.request().method() === 'PUT') {
      commits += 1
      await route.fulfill({ json: { project: { id: 'prj_split_text', stage: 'awaiting-confirmation', version: 3, input: { inputType: 'story', story: '原始故事', durationSec: 60, mode: 'automatic' } }, script } })
      return
    }
    previewAttempts += 1
    if (previewAttempts === 1) {
      await route.fulfill({ status: 502, json: { error: 'PROVIDER_UNAVAILABLE' } })
      return
    }
    await route.fulfill({ json: { script, summary: { scenes: 1, shots: 1, dialogue: 0, narration: 1, issues: [] }, expectedVersion: 2 } })
  })
  await page.goto('/')
  await page.locator('[aria-label="工作区导航"] button[aria-label="剧本"]').click()
  await expect(page.getByText('待拆分的故事文本。')).toBeVisible()
  await page.getByRole('button', { name: '拆分为剧本' }).click()
  await expect(page.getByRole('alert')).toContainText('模型服务请求失败或暂时不可用')
  await page.getByRole('button', { name: '重试拆分' }).click()
  await expect.poll(() => previewAttempts).toBe(2)
  await expect(page.getByRole('region', { name: '剧本拆分预览' })).toBeVisible()
  await expect(page.getByText('拆分后的剧本', { exact: true })).toBeVisible()
  expect(commits).toBe(0)
  await page.getByRole('button', { name: '确认并进入剧本编辑器' }).first().click()
  await expect(page.getByLabel('剧本标题')).toHaveValue('拆分后的剧本')
  expect(commits).toBe(1)
})

test('guided mode opens a bounded chat before showing the complete script', async ({ page }) => {
  const outline = {
    title: '隐藏初稿',
    scenes: [{ id: 'scene-1', title: '车站', shotIds: ['shot-1'] }],
    shots: [{ id: 'shot-1', order: 1, title: '姐姐回头', action: '回头', emotion: '惊讶', shotSize: '特写', durationSec: 30, visualDescription: '姐姐在最后一排回头', dialogue: '', narration: '' }],
  }
  let detailRequested = false
  const savedVersions: number[] = []
  await page.addInitScript(() => localStorage.setItem('comicflow-project-id', 'prj_chat_first'))
  await page.route('**/api/projects/prj_chat_first', (route) => route.fulfill({
    json: {
      project: {
        id: 'prj_chat_first', stage: 'awaiting-confirmation', version: 1,
        input: { inputType: 'story', story: '一个足够长的故事输入', durationSec: 60, mode: 'guided' },
        generationSession: { id: 'gen_chat_first', projectId: 'prj_chat_first', mode: 'guided', stage: 'awaiting-confirmation', status: 'ready', retryCount: 0, guided: { questionCount: 0, maxQuestions: 9, currentQuestion: '', transcript: [], done: false, detailGenerated: false } },
      },
      script: outline,
      jobs: [], visualAssets: [], audioAssets: [], lipSyncAssets: [], creditLedger: [],
    },
  }))
  await page.route('**/api/projects/prj_chat_first/script', async (route) => {
    if (route.request().method() === 'PATCH') {
      const body = route.request().postDataJSON() as { expectedVersion: number; script: typeof outline }
      savedVersions.push(body.expectedVersion)
      await route.fulfill({ json: { project: { id: 'prj_chat_first', stage: 'awaiting-confirmation', version: body.expectedVersion + 1 }, script: body.script } })
      return
    }
    await route.fulfill({ json: { project: { id: 'prj_chat_first', stage: 'awaiting-confirmation', version: 1 }, script: outline } })
  })
  await page.route('**/api/projects/prj_chat_first/script/guidance', (route) => route.fulfill({ json: { guided: { questionCount: 0, maxQuestions: 9, currentQuestion: '结尾要留下什么印象？', transcript: [], done: false } } }))
  await page.route('**/api/projects/prj_chat_first/script/guidance/answer', (route) => route.fulfill({ json: { guided: { questionCount: 1, maxQuestions: 9, currentQuestion: '主角最重要的情绪是什么？', transcript: [{ question: '结尾要留下什么印象？', answer: '留下悬念' }], done: false } } }))
  await page.route('**/api/projects/prj_chat_first/script/detail', async (route) => { detailRequested = true; await route.fulfill({ json: { project: { id: 'prj_chat_first', stage: 'awaiting-confirmation', version: 2 }, script: { ...outline, title: '完整剧本' } } }) })

  await page.goto('/')
  await expect(page.getByText('故事已收到')).toBeVisible()
  await expect(page.getByText('结尾要留下什么印象？')).toBeVisible()
  await expect(page.getByRole('button', { name: '发送回答' })).toBeVisible()
  await page.getByLabel('你的回答').fill('留下悬念')
  await page.getByRole('button', { name: '发送回答' }).click()
  await expect(page.getByText('主角最重要的情绪是什么？')).toBeVisible()
  await page.getByRole('button', { name: '直接生成当前剧本' }).click()
  await expect.poll(() => detailRequested).toBe(true)
  await expect(page.getByText('完整剧本')).toBeVisible()
  await page.getByLabel('剧本标题').fill('修改后的完整剧本')
  await page.getByRole('button', { name: '保存剧本草稿' }).click()
  await expect.poll(() => savedVersions).toEqual([2])
})

test('guided script remains visible when the first guidance request fails', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('comicflow-project-id', 'prj_guidance_error'))
  await page.route('**/api/projects/prj_guidance_error', (route) => route.fulfill({
    json: {
      project: {
        id: 'prj_guidance_error', stage: 'awaiting-confirmation', version: 1,
        input: { inputType: 'story', story: '一个足够长的故事输入', durationSec: 60, mode: 'guided' },
        generationSession: { id: 'gen_guidance_error', projectId: 'prj_guidance_error', mode: 'guided', stage: 'awaiting-confirmation', status: 'ready', retryCount: 0, guided: { questionCount: 0, maxQuestions: 9, currentQuestion: '', transcript: [], done: false, detailGenerated: false } },
      },
      script: { title: '已生成初稿', scenes: [], shots: [] },
      jobs: [], visualAssets: [], audioAssets: [], lipSyncAssets: [], creditLedger: [],
    },
  }))
  await page.route('**/api/projects/prj_guidance_error/script/guidance', (route) => route.fulfill({ status: 502, json: { error: 'PROVIDER_UNAVAILABLE' } }))

  await page.goto('/')
  await expect(page.getByRole('article').getByText('已生成初稿')).toBeVisible()
  await expect(page.getByRole('alert').filter({ hasText: '问答暂时不可用' })).toBeVisible()
  await expect(page.getByRole('button', { name: '重试问答' })).toBeVisible()
})

test('saved projects without guided session metadata still resume guided chat', async ({ page }) => {
  let guidanceRequests = 0
  await page.addInitScript(() => localStorage.setItem('comicflow-project-id', 'prj_legacy_guided'))
  await page.route('**/api/projects/prj_legacy_guided', (route) => route.fulfill({
    json: {
      project: { id: 'prj_legacy_guided', stage: 'awaiting-confirmation', version: 1, input: { inputType: 'story', story: '一个足够长的故事输入', durationSec: 60, mode: 'guided' } },
      script: { title: '旧项目剧本', scenes: [{ id: 'scene-1', title: '场景', shotIds: ['shot-1'] }], shots: [{ id: 'shot-1', order: 1, title: '镜头', action: '回头', emotion: '惊讶', shotSize: '特写', durationSec: 30, visualDescription: '画面', dialogue: '', narration: '' }] },
      jobs: [], visualAssets: [], audioAssets: [], lipSyncAssets: [], creditLedger: [],
    },
  }))
  await page.route('**/api/projects/prj_legacy_guided/script/guidance', (route) => { guidanceRequests += 1; return route.fulfill({ json: { guided: { questionCount: 0, maxQuestions: 9, currentQuestion: '旧项目问题？', transcript: [], done: false } } }) })
  await page.goto('/')
  await expect(page.getByText('一起完善你的剧情')).toBeVisible()
  await expect.poll(() => guidanceRequests).toBe(1)
  await expect(page.getByText('旧项目问题？')).toBeVisible()
})

test('creator can reopen a saved script preview from the project snapshot', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('comicflow-project-id', 'prj_saved_preview'))
  await page.route('**/api/projects/prj_saved_preview', (route) => route.fulfill({
    json: {
      project: { id: 'prj_saved_preview', stage: 'awaiting-confirmation', version: 2, input: { inputType: 'story', story: '一个足够长的故事输入', durationSec: 60, mode: 'automatic' } },
      script: { title: '已保存剧本', scenes: [{ id: 'scene-1', title: '车站', shotIds: ['shot-1'] }], shots: [{
        id: 'shot-1', order: 1, title: '回头', action: '回头', emotion: '惊讶', shotSize: '特写',
        durationSec: 30, visualDescription: '姐姐回头', dialogue: '', narration: '雨声',
      }] },
      jobs: [], visualAssets: [], audioAssets: [], lipSyncAssets: [], creditLedger: [],
    },
  }))

  await page.goto('/')
  await expect(page.locator('.preview-title-display')).toHaveText('已保存剧本')
})

test('saved automatic sessions show their script even when legacy input mode is absent', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('comicflow-project-id', 'prj_legacy_automatic'))
  await page.route('**/api/projects/prj_legacy_automatic', (route) => route.fulfill({
    json: {
      project: {
        id: 'prj_legacy_automatic', stage: 'script-completed', version: 1,
        generationSession: { id: 'gen_legacy', projectId: 'prj_legacy_automatic', mode: 'automatic', stage: 'script-completed', status: 'ready', retryCount: 0 },
      },
      script: { title: '旧自动剧本', scenes: [], shots: [] },
      jobs: [], visualAssets: [], audioAssets: [], lipSyncAssets: [], creditLedger: [],
    },
  }))

  await page.goto('/')
  await expect(page.locator('.preview-title-display')).toHaveText('旧自动剧本')
  await expect(page.getByText('一起完善你的剧情')).toHaveCount(0)
})

test('expired project ids are cleared without retrying the snapshot request', async ({ page }) => {
  let snapshotRequests = 0
  await page.addInitScript(() => localStorage.setItem('comicflow-project-id', 'prj_expired'))
  await page.route('**/api/projects/prj_expired', async (route) => {
    snapshotRequests += 1
    await route.fulfill({ status: 404, json: { error: 'PROJECT_NOT_FOUND' } })
  })

  await page.goto('/')
  await expect(page.getByText('你的创作会出现在这里')).toBeVisible()
  await page.waitForTimeout(1500)
  expect(snapshotRequests).toBe(1)
  await expect.poll(() => page.evaluate(() => localStorage.getItem('comicflow-project-id'))).toBeNull()
})

test('saved automatic projects do not offer guided mode switching', async ({ page }) => {
  let guidanceRequests = 0
  await page.addInitScript(() => localStorage.setItem('comicflow-project-id', 'prj_switch_guided'))
  await page.route('**/api/projects/prj_switch_guided', (route) => route.fulfill({
    json: {
      project: {
        id: 'prj_switch_guided', stage: 'script-completed', version: 1,
        input: { inputType: 'story', story: '一个足够长的故事输入', durationSec: 60, mode: 'automatic' },
        generationSession: { id: 'gen_switch', projectId: 'prj_switch_guided', mode: 'automatic', stage: 'script-completed', status: 'ready', retryCount: 0 },
      },
      script: { title: '自动剧本', scenes: [], shots: [] },
      jobs: [], visualAssets: [], audioAssets: [], lipSyncAssets: [], creditLedger: [],
    },
  }))
  await page.route('**/api/projects/prj_switch_guided/script/guidance', (route) => { guidanceRequests += 1; return route.fulfill({ json: { guided: { questionCount: 0, maxQuestions: 9, currentQuestion: '不应触发', transcript: [], done: false } } }) })
  await page.goto('/')
  await expect(page.getByText('一起完善你的剧情')).toHaveCount(0)
  await expect(page.getByText('逐步确认')).toHaveCount(0)
  await page.waitForTimeout(1200)
  expect(guidanceRequests).toBe(0)
})

test('creator can edit and save detailed script fields', async ({ page }) => {
  let saved: Record<string, unknown> | undefined
  await page.addInitScript(() => localStorage.setItem('comicflow-project-id', 'prj_editable'))
  await page.route('**/api/projects/prj_editable', (route) => route.fulfill({
    json: {
      project: { id: 'prj_editable', stage: 'awaiting-confirmation', version: 2 },
      script: { title: '原始剧本', scenes: [{ id: 'scene-1', title: '原始场景', shotIds: ['shot-1'] }], shots: [{
        id: 'shot-1', order: 1, title: '原始镜头', action: '站立', emotion: '紧张', shotSize: '中景', durationSec: 30,
        visualDescription: '原始画面', dialogue: '原始对白', narration: '原始旁白',
      }] }, jobs: [], visualAssets: [], audioAssets: [], lipSyncAssets: [], creditLedger: [],
    },
  }))
  await page.route('**/api/projects/prj_editable/script', async (route) => {
    if (route.request().method() === 'PATCH') {
      saved = route.request().postDataJSON() as Record<string, unknown>
      await route.fulfill({ json: { project: { id: 'prj_editable', stage: 'awaiting-confirmation', version: 3 }, script: (saved as { script: unknown }).script } })
      return
    }
    await route.fulfill({ status: 404, json: { error: 'NOT_FOUND' } })
  })
  await page.goto('/')
  await page.locator('[aria-label="工作区导航"] button[aria-label="剧本"]').click()
  await page.getByLabel('剧本标题').fill('修改后的剧本')
  await page.getByLabel('画面描述-shot-1').fill('修改后的画面')
  await page.getByLabel('对白-shot-1').fill('修改后的对白')
  await page.getByRole('button', { name: '保存剧本' }).click()
  await expect.poll(() => saved).toBeTruthy()
  expect((saved as { script: { title: string; shots: Array<{ visualDescription: string; dialogue: string }> } }).script.title).toBe('修改后的剧本')
  expect((saved as { script: { shots: Array<{ visualDescription: string; dialogue: string }> } }).script.shots[0].visualDescription).toBe('修改后的画面')
})

test('creator can choose automatic mode for a mock production run', async ({ page }) => {
  let requestedMode = ''
  let scriptRequests = 0
  await page.route('**/api/projects', async (route) => {
    const body = route.request().postDataJSON() as { mode: string }
    requestedMode = body.mode
    await route.fulfill({
      json: { project: { id: 'prj_auto', stage: 'story', version: 1 }, guestSession: { id: 'gst_auto', projectId: 'prj_auto' } },
    })
  })
  await page.route('**/api/projects/prj_auto/story', (route) => route.fulfill({
    json: { project: { id: 'prj_auto', stage: 'story-generated', version: 2, generatedStoryText: '自动故事文本。' }, storyText: '自动故事文本。' },
  }))
  await page.route('**/api/projects/prj_auto/script', async (route) => { scriptRequests += 1; await route.fulfill({ status: 500, json: { error: 'UNEXPECTED_SCRIPT_REQUEST' } }) })
  await page.goto('/')
  await page.getByText('全自动').click()
  await page.getByRole('button', { name: '生成故事文本' }).click()
  await expect.poll(() => requestedMode).toBe('automatic')
  expect(scriptRequests).toBe(0)
})

test('guided projects never call the automatic story endpoint', async ({ page }) => {
  let storyRequests = 0
  await page.addInitScript(() => localStorage.setItem('comicflow-project-id', 'prj_guided_mode'))
  await page.route('**/api/projects/prj_guided_mode', (route) => route.fulfill({
    json: {
      project: {
        id: 'prj_guided_mode', stage: 'awaiting-confirmation', version: 1,
        input: { inputType: 'story', story: '一个足够长的故事输入', durationSec: 60, mode: 'guided' },
        generationSession: { id: 'gen_guided_mode', projectId: 'prj_guided_mode', mode: 'guided', stage: 'awaiting-confirmation', status: 'ready', retryCount: 0, guided: { questionCount: 0, maxQuestions: 9, currentQuestion: '', transcript: [], done: true, detailGenerated: true } },
      },
      script: { title: '逐步剧本', scenes: [], shots: [] },
      jobs: [], visualAssets: [], audioAssets: [], lipSyncAssets: [], creditLedger: [],
    },
  }))
  await page.route('**/api/projects/prj_guided_mode/story', async (route) => { storyRequests += 1; await route.fulfill({ status: 500, json: { error: 'UNEXPECTED_STORY_REQUEST' } }) })
  await page.route('**/api/projects/prj_guided_mode/script/guidance', (route) => route.fulfill({ json: { guided: { questionCount: 0, maxQuestions: 9, currentQuestion: '', transcript: [], done: true, detailGenerated: true } } }))

  await page.goto('/')
  await expect(page.getByRole('article').getByText('逐步剧本')).toBeVisible()
  await page.waitForTimeout(1000)
  expect(storyRequests).toBe(0)
})

test('automatic mode skips guided questions and shows the complete script directly', async ({ page }) => {
  const script = {
    title: '自动初稿',
    scenes: [{ id: 'scene-1', title: '雨夜车站', shotIds: ['shot-1'] }],
    shots: [{
      id: 'shot-1', order: 1, title: '姐姐回头', action: '缓慢回头', emotion: '惊讶',
      shotSize: '特写', durationSec: 30, visualDescription: '末班车驶入雨夜车站',
      dialogue: '你终于来了。', narration: '',
    }],
  }
  await page.route('**/api/projects', (route) => route.fulfill({ json: { project: { id: 'prj_auto_detail', stage: 'story', version: 1, input: { mode: 'automatic' } }, guestSession: { id: 'gst_auto_detail', projectId: 'prj_auto_detail' } } }))
  await page.route('**/api/projects/prj_auto_detail/story', (route) => route.fulfill({ json: { project: { id: 'prj_auto_detail', stage: 'story-generated', version: 2, input: { mode: 'automatic' }, generatedStoryText: '自动生成的完整故事文本。' }, storyText: '自动生成的完整故事文本。' } }))
  await page.goto('/')
  await page.getByText('全自动').click()
  await page.getByRole('button', { name: '生成故事文本' }).click()
  await expect(page.getByLabel('生成的故事文本')).toHaveValue('自动生成的完整故事文本。')
  await expect(page.getByRole('button', { name: '进入剧本模块拆分' })).toBeVisible()
  await expect(page.getByLabel('剧本概览')).toHaveCount(0)
})

for (const structured of [false, true]) {
  test(`automatic generation streams before completion; structured=${structured}`, async ({ page }) => {
    await page.route('**/api/projects', route => route.fulfill({ json: {
      project: { id: 'prj_stream', stage: 'story', version: 1 }, guestSession: { id: 'gst_stream' },
    } }))
    const stream = await textStreamServer(page, '**/api/projects/prj_stream/story',
      structured ? '{"kind":"story_text","content":{"text":"第一幕正在展开' : '第一幕正在展开')
    try {
      await page.goto('/')
      await page.getByRole('button', { name: '生成故事文本', exact: true }).click()
      await expect(page.getByLabel('实时生成内容')).toContainText('第一幕正在展开')
      await expect(page.getByLabel('实时生成内容')).not.toContainText('story_text')
      await expect(page.getByLabel('生成的故事文本', { exact: true })).toHaveCount(0)
      stream.finish({ type: 'result', result: {
        project: { id: 'prj_stream', stage: 'story-generated', version: 2 }, storyText: '完整故事文本。',
      } })
      await expect(page.getByLabel('生成的故事文本', { exact: true })).toHaveValue('完整故事文本。')
      expect(stream.calls()).toBe(1)
    } finally { await stream.close() }
  })
}

test('creator can configure duration, quality and reference image before generation', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByLabel('视频时长')).toBeVisible()
  await page.getByLabel('视频时长').selectOption('90')
  await page.getByLabel('输出质量').selectOption('standard')
  await page.getByLabel('添加参考图').setInputFiles({
    name: 'reference.png',
    mimeType: 'image/png',
    buffer: Buffer.from('fake-png'),
  })
  await expect(page.getByText('reference.png')).toBeVisible()
})

test('storyboard does not expose unsupported no-op controls', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('comicflow-project-id', 'prj_storyboard'))
  await page.route('**/api/projects/prj_storyboard', (route) => route.fulfill({
    json: {
      project: { id: 'prj_storyboard', stage: 'awaiting-confirmation', version: 1 },
      script: { title: '雨夜', scenes: [{ id: 'scene-1', title: '车站', shotIds: ['shot-1'] }], shots: [{ id: 'shot-1', order: 1, title: '回头', durationSec: 6, shotSize: '中景', visualDescription: '车窗', action: '回头', dialogue: '', narration: '' }] },
      jobs: [], visualAssets: [], audioAssets: [], lipSyncAssets: [], creditLedger: [],
    },
  }))
  await page.goto('/')
  await page.getByRole('button', { name: '分镜' }).click()
  await expect(page.getByTitle('新增镜头')).toHaveCount(0)
  await expect(page.getByRole('button', { name: '复制' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '保存' })).toHaveCount(0)
})

test('creator can sign in and claim the current project', async ({ page }) => {
  let claimed = false
  await page.addInitScript(() => localStorage.setItem('comicflow-project-id', 'prj_auth'))
  await page.route('**/api/projects/prj_auth', (route) => route.fulfill({ json: { project: { id: 'prj_auth', stage: 'story', version: 1 }, jobs: [], creditLedger: [] } }))
  await page.route('**/api/projects/prj_auth/claim', async (route) => {
    claimed = true
    await route.fulfill({ json: { project: { id: 'prj_auth', ownerUserId: 'user_creator@example.com' } } })
  })
  await page.route('**/api/auth/magic-link', (route) => route.fulfill({ json: { email: 'creator@example.com', token: 'dev-token' } }))
  await page.route('**/api/auth/verify', (route) => route.fulfill({ json: { userId: 'user_creator@example.com', email: 'creator@example.com' } }))
  await page.route('**/api/projects/prj_auth/credits', (route) => route.fulfill({ json: { available: 100, ledger: [] } }))
  await page.goto('/')
  await page.getByRole('button', { name: '登录/认领' }).click()
  await page.getByRole('dialog', { name: '登录并认领项目' }).getByLabel('邮箱').fill('creator@example.com')
  await page.getByRole('button', { name: '发送登录链接' }).click()
  await page.getByRole('dialog', { name: '登录并认领项目' }).getByLabel('验证码').fill('dev-token')
  await page.getByRole('button', { name: '验证并认领' }).click()
  await expect.poll(() => claimed).toBe(true)
  await expect(page.getByText('100 Credits')).toBeVisible()
})

test('creator sees moderation block when story is rejected', async ({ page }) => {
  await page.route('**/api/projects', (route) => route.fulfill({ json: { project: { id: 'prj_block', stage: 'story', version: 1 }, guestSession: { id: 'gst_block', projectId: 'prj_block' } } }))
  await page.route('**/api/projects/prj_block/story', (route) => route.fulfill({ status: 422, json: { error: 'MODERATION_BLOCKED' } }))
  await page.goto('/')
  await page.getByText('全自动').click()
  await page.getByRole('button', { name: '生成故事文本' }).click()
  await expect(page.getByRole('alert').filter({ hasText: 'MODERATION_BLOCKED' })).toBeVisible()
})

test('creator sees insufficient credits when story generation is blocked', async ({ page }) => {
  await page.route('**/api/projects', (route) => route.fulfill({ json: { project: { id: 'prj_credit', stage: 'story', version: 1 }, guestSession: { id: 'gst_credit', projectId: 'prj_credit' } } }))
  await page.route('**/api/projects/prj_credit/story', (route) => route.fulfill({ status: 409, json: { error: 'INSUFFICIENT_CREDIT' } }))
  await page.goto('/')
  await page.getByText('全自动').click()
  await page.getByRole('button', { name: '生成故事文本' }).click()
  await expect(page.getByRole('alert').filter({ hasText: 'INSUFFICIENT_CREDIT' })).toBeVisible()
})
