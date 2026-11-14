import { expect, test } from '@playwright/test'

test('H3 Chinese optimization is explicit and saving does not generate', async ({ page }) => {
  const unexpected: string[] = []
  let saved: Record<string, unknown> = {
    provider: 'compshare-h3', baseUrl: 'https://h3.test', model: 'MiniMax-H3',
    timeoutMs: 600000, enabled: true, configured: true, apiKeyMasked: '********',
    resolution: '768P', h3PromptMode: 'local-skill',
  }
  await page.route('**/api/**', route => {
    if (route.request().method() !== 'GET') unexpected.push(route.request().url())
    return route.fulfill({ json: {} })
  })
  await page.route('**/api/provider-config', route => route.fulfill({ json: {
    text: { enabled: false, configured: false, apiKeyMasked: '' }, video: saved,
    runtime: { h3Prompt: saved.h3PromptMode === 'context-ir' ? '中文 + 优云 Context-IR' : 'text + h3-prompt-writing' },
  } }))
  await page.route('**/api/provider-config/profiles/video/production', route => {
    const payload = route.request().postDataJSON()
    expect(payload.apiKey).toBeUndefined()
    saved = { ...saved, ...payload }
    return route.fulfill({ json: saved })
  })
  await page.goto('/')
  await page.getByRole('button', { name: '模型 API' }).click()
  await page.getByRole('button', { name: '查看旧双槽配置', exact: true }).click()
  const section = page.getByRole('article', { name: '视频 API', exact: true })
  await expect(section.getByLabel('H3 提示词处理')).toHaveValue('local-skill')
  await section.getByLabel('H3 提示词处理').selectOption('context-ir')
  await expect(section.getByText('中文剧本、动作、对白', { exact: false })).toBeVisible()
  await section.getByRole('button', { name: '保存视频配置' }).click()
  await expect(section.getByRole('status')).toContainText('已保存并生效')
  expect(saved.h3PromptMode).toBe('context-ir')
  expect(saved.resolution).toBe('768P')
  await page.getByRole('button', { name: '关闭', exact: true }).click()
  await page.getByRole('button', { name: '模型 API' }).click()
  await page.getByRole('button', { name: '查看旧双槽配置', exact: true }).click()
  await expect(section.getByLabel('H3 提示词处理')).toHaveValue('context-ir')
  await section.getByLabel('H3 提示词处理').selectOption('local-skill')
  await section.getByRole('button', { name: '保存视频配置' }).click()
  await expect(section.getByRole('status')).toContainText('未调用模型')
  expect(saved.h3PromptMode).toBe('local-skill')
  expect(unexpected).toEqual([])
})
