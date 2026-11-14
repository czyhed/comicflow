import assert from 'node:assert/strict'
import test from 'node:test'
import { loadApiClient } from './helpers/load-api-client.mjs'

const { request } = await loadApiClient()

for (const [validation, wording] of [
  [{ rule: 'shot_count', path: 'shots', actual: 7, min: 8, max: 10 }, '实际7个，要求8–10个'],
  [{ rule: 'scene_count', path: 'scenes', actual: 2, min: 3, max: 3 }, '实际2个，要求3个'],
  [{ rule: 'text_type', path: 'shots[0].dialogue' }, 'shots[0].dialogue：必须是文本字符串'],
  [{ rule: 'shot_references', path: 'scenes' }, '镜头引用存在遗漏、重复或不存在的镜头'],
  [{ rule: 'routing', path: 'envelope' }, '返回的任务标识与剧本拆分不一致'],
  [{ rule: 'private', path: 'private-key' }, '镜头数量或场景引用'],
  [{ rule: 'shot_count', path: 'private-key', actual: 'private', min: 8, max: 10 }, '镜头数量不符合本次要求'],
]) {
  test(`contract diagnosis ${JSON.stringify(validation)} is safe and actionable`, async t => {
    let calls = 0
    t.mock.method(globalThis, 'fetch', async () => {
      calls++
      return new Response(JSON.stringify({ error: 'PROVIDER_INVALID_RESPONSE',
        stage: 'script_split', reason: 'script_contract_invalid', validation }), { status: 502 })
    })
    const previous = Object.getOwnPropertyDescriptor(globalThis, 'localStorage')
    Object.defineProperty(globalThis, 'localStorage', { value: { getItem: () => null }, configurable: true })
    t.after(() => {
      if (previous) Object.defineProperty(globalThis, 'localStorage', previous)
      else delete globalThis.localStorage
    })
    await assert.rejects(request('/api/projects/test/script/preview', { method: 'POST' }), error => {
      assert.ok(error.message.includes(wording), error.message)
      assert.match(error.message, /故事已保留/)
      assert.doesNotMatch(error.message, /private/)
      return true
    })
    assert.equal(calls, 1)
  })
}

for (const [reason, wording] of [
  ['output_truncated', '长度限制被截断'],
  ['reasoning_only', '只返回了思考内容'],
  ['empty_content', '正文为空'],
  ['invalid_json', '不是完整可解析的 JSON'],
  ['script_contract_invalid', '镜头数量或场景引用'],
  ['private-unknown-value', '返回内容未通过校验'],
]) {
  test(`script response failure identifies ${reason} without retry`, async t => {
    let calls = 0
    t.mock.method(globalThis, 'fetch', async () => {
      calls++
      return new Response(JSON.stringify({ error: 'PROVIDER_INVALID_RESPONSE',
        stage: 'script_split', reason }), { status: 502 })
    })
    const previous = Object.getOwnPropertyDescriptor(globalThis, 'localStorage')
    Object.defineProperty(globalThis, 'localStorage', { value: { getItem: () => null }, configurable: true })
    t.after(() => {
      if (previous) Object.defineProperty(globalThis, 'localStorage', previous)
      else delete globalThis.localStorage
    })
    await assert.rejects(request('/api/projects/test/script/preview', { method: 'POST' }), error => {
      assert.ok(error.message.includes(wording))
      assert.match(error.message, /故事已保留/)
      assert.match(error.message, /未自动重试/)
      assert.match(error.message, /可能已计费/)
      assert.doesNotMatch(error.message, /private/)
      return true
    })
    assert.equal(calls, 1)
  })
}

for (const phase of ['read', 'connect']) {
  test(`script preview ${phase} timeout identifies text budget without retry`, async t => {
    let calls = 0
    t.mock.method(globalThis, 'fetch', async () => {
      calls++
      return new Response(JSON.stringify({ error: 'PROVIDER_TIMEOUT', stage: 'script_split',
        reason: 'timeout', timeoutMs: 300000, timeoutPhase: phase }), { status: 504 })
    })
    const previous = Object.getOwnPropertyDescriptor(globalThis, 'localStorage')
    Object.defineProperty(globalThis, 'localStorage', { value: { getItem: () => null }, configurable: true })
    t.after(() => {
      if (previous) Object.defineProperty(globalThis, 'localStorage', previous)
      else delete globalThis.localStorage
    })
    await assert.rejects(request('/api/projects/test/script/preview', { method: 'POST' }), error => {
      assert.match(error.message, /剧本拆分失败/)
      assert.match(error.message, /300 秒/)
      assert.match(error.message, /未保存拆分结果/)
      assert.match(error.message, /可能已计费/)
      assert.match(error.message, /用途选择/)
      assert.match(error.message, /未自动重试/)
      assert.doesNotMatch(error.message, /视频/)
      return true
    })
    assert.equal(calls, 1)
  })
}

test('character timeout identifies the bound text model without starting media', async t => {
  t.mock.method(globalThis, 'fetch', async () => new Response(JSON.stringify({
    error: 'PROVIDER_TIMEOUT', stage: 'character_prompt', reason: 'timeout', timeoutMs: 300000,
  }), { status: 504 }))
  const previous = Object.getOwnPropertyDescriptor(globalThis, 'localStorage')
  Object.defineProperty(globalThis, 'localStorage', { value: { getItem: () => null }, configurable: true })
  t.after(() => {
    if (previous) Object.defineProperty(globalThis, 'localStorage', previous)
    else delete globalThis.localStorage
  })
  await assert.rejects(request('/api/projects/test/characters/prompt-preview'), error => {
    assert.match(error.message, /人物提示词生成失败/)
    assert.match(error.message, /300 秒/)
    assert.match(error.message, /未保存提示词/)
    assert.match(error.message, /用途选择 → 人物提示词/)
    assert.match(error.message, /未调用图片或视频模型/)
    assert.match(error.message, /可能已计费/)
    return true
  })
})
