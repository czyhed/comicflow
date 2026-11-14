import { expect, test, type Page } from '@playwright/test'
import type { ModelCatalog } from '../../src/api/modelRegistry'

async function registry(page: Page) {
  const catalog: ModelCatalog = {
    revision: 0, scope: 'postgresql', connections: [], models: [], bindings: {},
    usages: { story: '故事生成', script: '剧本拆分', 'image-edit': '参考图/三视图编辑', video: '镜头视频' },
    templates: {
      'chat-completions': { name: 'Chat Completions 兼容文本', usages: ['story', 'script'], defaults: { timeoutMs: 120000 } },
      'compshare-h3': { name: '优云 MiniMax H3', usages: ['video'], defaults: { resolution: '768P', h3PromptMode: 'context-ir' } },
      'xiangongyun-h3': { name: '仙宫云 MiniMax H3', usages: ['video'], defaults: { timeoutMs: 600000, resolution: '0.5P', h3PromptMode: 'context-ir', inferenceProfile: 'turbo8_av_sol_gpu_te' } },
    },
  }
  const writes: { url: string; body: Record<string, unknown> }[] = []
  await page.route('**/api/**', route => route.fulfill({ json: {} }))
  await page.route('**/api/provider-config', route => route.fulfill({ json: {
    text: { configured: false, enabled: false, apiKeyMasked: '' },
    image: { configured: false, enabled: false, apiKeyMasked: '' },
    video: { configured: false, enabled: false, apiKeyMasked: '' },
  } }))
  await page.route('**/api/model-registry**', async route => {
    const request = route.request()
    const url = request.url()
    if (request.method() === 'GET') return route.fulfill({ json: catalog })
    const body = request.postData() ? request.postDataJSON() : {}
    writes.push({ url, body })
    if (url.endsWith('/connections')) {
      catalog.connections.push({ id: 'connection-1', name: body.name, baseUrl: body.baseUrl, configured: Boolean(body.apiKey) })
    } else if (url.endsWith('/models')) {
      catalog.models.push({ ...body, id: `model-${catalog.models.length + 1}` })
    } else if (url.endsWith('/bindings')) {
      catalog.bindings = body.bindings
    } else if (url.endsWith('/preview')) {
      return route.fulfill({ json: { networkCalled: false, body: { model: 'custom-model', messages: [] } } })
    }
    catalog.revision++
    await route.fulfill({ json: catalog })
  })
  await page.goto('/')
  await page.getByRole('button', { name: '模型 API', exact: true }).click()
  await expect(page.getByRole('heading', { name: '模型管理', exact: true })).toBeVisible()
  return { catalog, writes }
}

test('save a shared connection, keep multiple models and independently bind purposes', async ({ page }) => {
  const { writes } = await registry(page)
  await page.getByRole('button', { name: '先添加连接' }).click()
  await page.getByLabel('连接名称', { exact: true }).fill('我的方舟')
  await page.getByLabel('API 基础地址').fill('https://example.test/v3')
  await page.getByLabel('API Key', { exact: true }).fill('offline-private-key')
  await page.getByRole('button', { name: '保存连接', exact: true }).click()
  await page.getByRole('button', { name: '新增模型', exact: true }).click()
  await page.getByLabel('显示名称').fill('剧本模型')
  await page.getByLabel('API 模型 ID').fill('custom-model')
  await page.getByRole('button', { name: '保存模型', exact: true }).click()
  await expect(page.getByRole('article', { name: '剧本模型', exact: true })).toBeVisible()
  await page.getByRole('button', { name: '复制 剧本模型', exact: true }).click()
  await page.getByLabel('显示名称').fill('低成本模型')
  await page.getByLabel('API 模型 ID').fill('custom-lite')
  await page.getByRole('button', { name: '保存模型', exact: true }).click()
  await expect(page.getByRole('article', { name: '低成本模型', exact: true })).toBeVisible()
  await page.getByRole('button', { name: '用途选择', exact: true }).click()
  await page.getByLabel('故事生成', { exact: true }).selectOption('model-2')
  await expect(page.getByRole('status')).toContainText('故事生成已更新')
  await page.getByLabel('剧本拆分', { exact: true }).selectOption('model-1')
  await expect(page.getByRole('status')).toContainText('剧本拆分已更新')
  expect(writes.filter(w => w.body.apiKey)).toHaveLength(1)
  expect(writes.filter(w => w.url.endsWith('/models')).map(w => w.body.connectionId)).toEqual(['connection-1', 'connection-1'])
  expect(writes.at(-1)?.body.bindings).toEqual({ story: 'model-2', script: 'model-1' })
  await expect(page.getByLabel('参考图/三视图编辑')).not.toContainText('剧本模型')
  await page.getByRole('button', { name: '模型列表', exact: true }).click()
  await page.screenshot({ path: '../var/model-registry-console.png', fullPage: true })
})

test('xiangongyun uses an existing connection and saves video defaults without generation', async ({ page }) => {
  const { catalog, writes } = await registry(page)
  catalog.connections.push({ id: 'connection-1', name: '仙宫云', baseUrl: 'https://instance.test', configured: true })
  await page.getByRole('button', { name: '刷新模型库' }).click()
  await page.getByRole('button', { name: '新增模型', exact: true }).click()
  await page.getByLabel('显示名称').fill('仙宫云视频')
  await page.getByLabel('调用协议').selectOption('xiangongyun-h3')
  await page.getByLabel('API 模型 ID').fill('MiniMax-H3')
  await expect(page.getByText(/选择已保存的仙宫云连接/)).toBeVisible()
  await expect(page.getByLabel('调用参数 JSON', { exact: true })).toHaveValue(/"resolution": "0.5P"/)
  await page.getByLabel('仙宫云分辨率', { exact: true }).selectOption('0.8P')
  await expect(page.getByLabel('调用参数 JSON', { exact: true })).toHaveValue(/"resolution": "0.8P"/)
  await page.getByLabel('仙宫云推理档位', { exact: true }).selectOption('quality_av_sol_gpu_te')
  await page.getByRole('button', { name: '保存模型', exact: true }).click()
  await page.getByRole('button', { name: '用途选择', exact: true }).click()
  await page.getByLabel('镜头视频', { exact: true }).selectOption('model-1')
  await expect(page.getByRole('status')).toContainText('镜头视频已更新')
  expect(writes.map(w => new URL(w.url).pathname)).toEqual(['/api/model-registry/models', '/api/model-registry/bindings'])
  expect(writes[0].body).toMatchObject({ protocol: 'xiangongyun-h3', connectionId: 'connection-1', config: { timeoutMs: 600000, resolution: '0.8P', h3PromptMode: 'context-ir', inferenceProfile: 'quality_av_sol_gpu_te' } })
  expect(writes.some(w => w.body.apiKey)).toBe(false)
})

test('bad JSON never saves; offline preview never uses a generation endpoint', async ({ page }) => {
  const { catalog, writes } = await registry(page)
  catalog.connections.push({ id: 'connection-1', name: '已配置', baseUrl: 'https://example.test', configured: true })
  await page.getByRole('button', { name: '刷新模型库' }).click()
  await page.getByRole('button', { name: '新增模型', exact: true }).click()
  await page.getByLabel('显示名称').fill('可预览模型')
  await page.getByLabel('API 模型 ID').fill('custom-model')
  await page.getByLabel('调用参数 JSON', { exact: true }).fill('{broken')
  await page.getByRole('button', { name: '保存模型', exact: true }).click()
  await expect(page.getByRole('dialog', { name: '模型管理' }).getByRole('alert')).toContainText('JSON 格式错误')
  expect(writes).toHaveLength(0)
  await page.getByRole('button', { name: '填入请求模板', exact: true }).click()
  await page.screenshot({ path: '../var/model-registry-editor.png', fullPage: true })
  await page.getByRole('button', { name: '保存模型', exact: true }).click()
  await page.getByRole('button', { name: '离线预览', exact: true }).click()
  await expect(page.getByText('离线预览 · 未发送请求', { exact: true })).toBeVisible()
  expect(writes.map(w => new URL(w.url).pathname)).toEqual(['/api/model-registry/models', '/api/model-registry/models/model-1/preview'])
  await expect(page.getByRole('dialog', { name: '模型管理' })).not.toContainText('offline-private-key')
})

test('connection tests run only on click and distinguish model errors from address reachability', async ({ page }) => {
  const { catalog, writes } = await registry(page)
  catalog.connections.push({ id: 'c', name: '测试方舟', baseUrl: 'https://example.test/v3', configured: true })
  catalog.models.push({ id: 'm', name: '故事模型', connectionId: 'c', model: 'text-demo', protocol: 'chat-completions', enabled: true, config: {} })
  const probes: Record<string, unknown>[] = []
  await page.route('**/api/model-registry/connections/c/test', async route => {
    const payload = route.request().postDataJSON()
    probes.push(payload)
    await route.fulfill({ json: payload.modelId ? {
      status: 'failed', scope: 'text', message: '供应商不接受请求参数', model: 'text-demo',
      parameter: 'max_tokens', upstreamStatus: 400, elapsedMs: 100, revision: 0,
    } : {
      status: 'partial', scope: 'address', message: '仅证明地址可达，未验证 Key、模型或生成能力。',
      upstreamStatus: 404, elapsedMs: 30, revision: 0,
    } })
  })
  await page.getByRole('button', { name: '刷新模型库' }).click()
  await page.getByRole('button', { name: '连接与密钥', exact: true }).click()
  const card = page.getByRole('article', { name: '测试方舟', exact: true })
  await expect(card).toContainText('供应商可能计费')
  expect(probes).toHaveLength(0)
  await card.getByRole('button', { name: '测试连接', exact: true }).click()
  await expect(card.getByRole('alert')).toContainText('HTTP 400')
  await expect(card.getByRole('alert')).toContainText('max_tokens')
  expect(probes[0]).toEqual({ revision: 0, modelId: 'm' })
  await page.getByLabel('测试方舟测试方式').selectOption('')
  await card.getByRole('button', { name: '测试连接', exact: true }).click()
  await expect(card.getByRole('status')).toContainText('模型尚未验证')
  expect(probes).toHaveLength(2)
  expect(writes).toHaveLength(0)
})
