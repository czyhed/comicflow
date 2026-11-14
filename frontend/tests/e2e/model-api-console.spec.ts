import { expect, test } from '@playwright/test'

test('text provider console saves configuration and shows masked status', async ({ page }) => {
  let saved: Record<string, unknown> | undefined
  let text = { configured: false, enabled: false, apiKeyMasked: '' }
  await page.route('**/api/provider-config', route => route.fulfill({ json: { text } }))
  await page.route('**/api/provider-config/profiles/text/production', async route => {
    saved = route.request().postDataJSON()
    text = { ...saved, configured: true, enabled: true, apiKeyMasked: '********' }
    await route.fulfill({ json: text })
  })
  await page.goto('/')
  await page.getByRole('button', { name: '模型 API' }).click()
  await page.getByRole('button', { name: '查看旧双槽配置', exact: true }).click()
  const section = page.getByRole('article', { name: '文本 / 剧本 API' })
  await section.getByLabel('API 地址').fill('https://provider.test/v1')
  await section.getByLabel('API Key').fill('secret-key')
  await section.getByLabel('模型名称').fill('script-v1')
  await section.getByLabel('启用文本 API').check()
  await section.getByRole('button', { name: '保存文本配置' }).click()
  await expect(section.getByRole('status')).toContainText('已保存并生效')
  expect(saved?.apiKey).toBe('secret-key')
  await expect(section.getByLabel('API Key')).toHaveValue('')
})

test('text connectivity check names the refusal instead of spending a generation', async ({ page }) => {
  const calls: string[] = []
  await page.route('**/api/**', route => route.fulfill({ json: {} }))
  await page.route('**/api/provider-config', route => route.fulfill({ json: {
    text: { provider: 'doubao', baseUrl: 'https://ark.test/api/v3', model: 'Doubao-Seed-2.1-turbo', enabled: true, configured: true, apiKeyMasked: '********' },
  } }))
  await page.route('**/api/provider-config/text/test', route => {
    calls.push(route.request().method())
    return route.fulfill({ status: 400, json: {
      error: 'PROVIDER_REQUEST_INVALID', stage: 'text_check',
      upstreamStatus: 404, reason: 'model_not_enabled', parameter: 'model',
    } })
  })
  await page.goto('/')
  await page.getByRole('button', { name: '模型 API' }).click()
  await page.getByRole('button', { name: '查看旧双槽配置', exact: true }).click()
  const section = page.getByRole('article', { name: '文本 / 剧本 API' })
  await section.getByRole('button', { name: '测试文本连通性' }).click()
  await expect(section.getByRole('alert')).toContainText('当前账号尚未开通该模型')
  await expect(section.getByRole('alert')).toContainText('上游 HTTP 404')
  expect(calls).toEqual(['POST'])
})

test('text connectivity check reports the model that answered', async ({ page }) => {
  await page.route('**/api/**', route => route.fulfill({ json: {} }))
  await page.route('**/api/provider-config', route => route.fulfill({ json: {
    text: { provider: 'bailian', baseUrl: 'https://provider.test/v1', model: 'qwen-plus', enabled: true, configured: true, apiKeyMasked: '********' },
  } }))
  await page.route('**/api/provider-config/text/test', route => route.fulfill({ json: { ok: true, model: 'qwen-plus-2026' } }))
  await page.goto('/')
  await page.getByRole('button', { name: '模型 API' }).click()
  await page.getByRole('button', { name: '查看旧双槽配置', exact: true }).click()
  const section = page.getByRole('article', { name: '文本 / 剧本 API' })
  await section.getByRole('button', { name: '测试文本连通性' }).click()
  await expect(section.getByRole('status')).toContainText('连通性正常：qwen-plus-2026')
  await expect(section.getByRole('status')).toContainText('未调用生成模型')
})

test('a timed out connectivity check names the budget that ran out', async ({ page }) => {
  await page.route('**/api/**', route => route.fulfill({ json: {} }))
  await page.route('**/api/provider-config', route => route.fulfill({ json: {
    text: { provider: 'doubao', baseUrl: 'https://ark.test/api/v3', model: 'Doubao-Seed-2.1-turbo', enabled: true, configured: true, apiKeyMasked: '********' },
  } }))
  await page.route('**/api/provider-config/text/test', route => route.fulfill({ status: 504, json: {
    error: 'PROVIDER_TIMEOUT', stage: 'text_check', reason: 'timeout', timeoutMs: 120000,
  } }))
  await page.goto('/')
  await page.getByRole('button', { name: '模型 API' }).click()
  await page.getByRole('button', { name: '查看旧双槽配置', exact: true }).click()
  const section = page.getByRole('article', { name: '文本 / 剧本 API' })
  await section.getByRole('button', { name: '测试文本连通性' }).click()
  await expect(section.getByRole('alert')).toContainText('上游请求超时')
  await expect(section.getByRole('alert')).toContainText('120000 毫秒')
})

test('test and production profiles switch independently without generation', async ({ page }) => {
  const configs: Record<string, Record<string, unknown>> = {}
  const profiles: Record<string, { active: string; test: Record<string, unknown>; production: Record<string, unknown> }> = {}
  const unexpected: string[] = []
  await page.route('**/api/**', route => {
    if (route.request().method() !== 'GET') unexpected.push(route.request().url())
    return route.fulfill({ json: {} })
  })
  await page.route('**/api/provider-config', route => route.fulfill({ json: {
    text: { configured: false, enabled: false, apiKeyMasked: '' }, ...configs, profiles,
  } }))
  await page.route('**/api/provider-config/profiles/**', route => {
    const parts = new URL(route.request().url()).pathname.split('/')
    const capability = parts[4], slot = parts[5] as 'test' | 'production'
    profiles[capability] ??= { active: 'production', test: {}, production: {} }
    if (route.request().method() === 'POST') {
      profiles[capability].active = slot
      configs[capability] = profiles[capability][slot]
    } else {
      const { apiKey, ...profile } = route.request().postDataJSON()
      profiles[capability][slot] = { ...profile, configured: Boolean(apiKey) || profiles[capability][slot].configured, apiKeyMasked: '********' }
      if (profiles[capability].active === slot) configs[capability] = profiles[capability][slot]
    }
    return route.fulfill({ json: profiles[capability][slot] })
  })
  await page.goto('/')
  await page.getByRole('button', { name: '模型 API' }).click()
  await page.getByRole('button', { name: '查看旧双槽配置', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '模型 API 配置' })
  for (const [capability, title] of [['image', '角色 / 场景图片 API'], ['video', '视频 API']]) {
    const section = dialog.getByRole('article', { name: title, exact: true })
    await section.getByLabel('API Key').fill(capability + '-production')
    await section.getByRole('checkbox').check()
    await section.getByRole('button', { name: capability === 'image' ? '保存图片配置' : '保存视频配置' }).click()
    await expect(section.getByRole('status')).toContainText('未调用模型')
    await section.getByLabel(`${capability}-编辑配置`).selectOption('test')
    await section.getByLabel('API Key').fill(capability + '-test')
    await section.getByRole('checkbox').check()
    await section.getByRole('button', { name: capability === 'image' ? '保存图片配置' : '保存视频配置' }).click()
    await expect(section.getByRole('status')).toContainText('尚未切换')
    expect(profiles[capability].active).toBe('production')
    await section.getByRole('button', { name: '切换使用测试配置' }).click()
    await expect(section.getByText('当前：测试配置', { exact: false })).toBeVisible()
    expect(configs[capability].model).toBe(capability === 'image' ? 'wan2.2-t2i-flash' : 'wan2.2-i2v-flash')
    await section.getByLabel(`${capability}-编辑配置`).selectOption('production')
    await expect(section.getByLabel('API Key')).toHaveValue('')
    await section.getByRole('button', { name: '切换使用正式配置' }).click()
    await expect(section.getByText('当前：正式配置', { exact: false })).toBeVisible()
  }
  const video = dialog.getByRole('article', { name: '视频 API', exact: true })
  await expect(video.getByLabel('模型名称')).toHaveValue('MiniMax-H3')
  await video.getByLabel('供应商').selectOption('bailian-video')
  await video.getByRole('checkbox').check()
  await expect(video.getByRole('button', { name: '保存视频配置' })).toBeDisabled()
  await expect(video.getByLabel('API Key')).toHaveAttribute('placeholder', '仅本次保存时提交')
  await page.screenshot({ path: test.info().outputPath('profiles.png'), fullPage: true })
  expect(unexpected).toEqual([])
})

test('all model names remain user controlled and image protocol paths are editable', async ({ page }) => {
  const saved: Record<string, Record<string, unknown>> = {}
  const unexpected: string[] = []
  await page.route('**/api/**', route => {
    if (route.request().method() !== 'GET') unexpected.push(route.request().url())
    return route.fulfill({ json: {} })
  })
  await page.route('**/api/provider-config', route => route.fulfill({ json: saved }))
  await page.route('**/api/provider-config/profiles/*/production', route => {
    const capability = new URL(route.request().url()).pathname.split('/')[4]
    const { apiKey: _secret, ...profile } = route.request().postDataJSON()
    saved[capability] = { ...profile, enabled: true, configured: true, apiKeyMasked: '********' }
    return route.fulfill({ json: saved[capability] })
  })
  await page.goto('/')
  await page.getByRole('button', { name: '模型 API' }).click()
  await page.getByRole('button', { name: '查看旧双槽配置', exact: true }).click()
  for (const [capability, title] of [['text', '文本 / 剧本 API'], ['image', '角色 / 场景图片 API'], ['video', '视频 API']]) {
    const section = page.getByRole('article', { name: title, exact: true })
    const model = `${capability}-my-deployment`
    await section.getByLabel('模型名称').fill(` ${model} `)
    await section.getByLabel('API 地址').fill('https://custom.test/api/v1')
    if (capability === 'video') await section.getByLabel('供应商').selectOption('bailian-video')
    if (capability === 'image') await section.getByLabel('图片接口协议').selectOption('wan26-image')
    await expect(section.getByLabel('模型名称')).toHaveValue(` ${model} `)
    await expect(section.getByLabel('API 地址')).toHaveValue('https://custom.test/api/v1')
    if (capability !== 'text') {
      await section.getByLabel('自定义提交路径').fill('/custom/generate')
      await section.getByLabel('自定义查询路径').fill('/custom/jobs/{task_id}')
    }
    await section.getByLabel('API Key').fill('offline')
    await section.getByRole('checkbox').check()
    await section.getByRole('button', { name: `保存${capability === 'text' ? '文本' : capability === 'image' ? '图片' : '视频'}配置` }).click()
    await expect(section.getByRole('status')).toContainText('已保存并生效')
    expect(saved[capability].model).toBe(model)
    if (capability !== 'text') expect(saved[capability].requestPath).toBe('/custom/generate')
    if (capability === 'image') expect(saved[capability].imageProtocol).toBe('wan26-image')
  }
  expect(unexpected).toEqual([])
})
