import assert from 'node:assert/strict'
import test from 'node:test'
import { loadApiClient } from './helpers/load-api-client.mjs'

// Exercise the real client with an in-memory response; no browser/API is contacted.
const { comicflowApi } = await loadApiClient()

const cases = [
  ['tts', 'authentication', undefined, 'PROVIDER_AUTH_FAILED', '配音服务鉴权失败', undefined],
  ['h3_submit', 'authentication', 401, 'PROVIDER_AUTH_FAILED', '视频提交失败', undefined],
  ['h3_poll', 'rate_limited', 429, 'VIDEO_RATE_LIMITED', '任务已提交，查询失败', 'known-task-1'],
  ['h3_result', 'service_error', 503, 'PROVIDER_UNAVAILABLE', '视频下载失败', 'known-task-1'],
  ['h3_submit', 'timeout', undefined, 'PROVIDER_TIMEOUT', '视频提交失败', undefined],
  ['h3_submit', 'business_rejected', 400, 'VIDEO_REQUEST_INVALID', '网关未创建视频任务', undefined],
  ['h3_poll', 'business_rejected', 400, 'VIDEO_REQUEST_INVALID', '网关拒绝查询已有任务', 'known-task-1'],
  ['h3_poll', 'task_cancelled', undefined, 'VIDEO_TASK_CANCELLED', 'H3 视频任务已取消', 'known-task-1'],
  ['h3_poll', 'task_failed', undefined, 'VIDEO_GENERATION_FAILED', 'H3 视频任务生成失败', 'known-task-1'],
  ['h3_text', 'rate_limited', 429, 'PROVIDER_RATE_LIMITED', '尚未提交 H3 视频', undefined],
  ['h3_text', 'connection_error', undefined, 'PROVIDER_UNAVAILABLE', '连接中断', undefined],
  ...[
    ['empty_content', '未返回正文'], ['reasoning_only', '只返回了推理内容'],
    ['invalid_envelope', 'HTTP 响应不是 JSON'], ['invalid_json', '正文不符合 JSON 格式'],
    ['content_refused', '明确拒绝输出'], ['content_not_text', '正文类型不是文本'],
    ['output_truncated', '扩写输出被截断'], ['message_missing', '缺少有效的 message'],
  ].map(([reason, label]) => ['h3_text', reason, undefined, 'PROVIDER_INVALID_RESPONSE', label]),
]

for (const [stage, reason, upstreamStatus, error, label, taskId] of cases) {
  test(`${stage} ${reason}: names the failure without retrying`, async (t) => {
    let requests = 0
    t.mock.method(globalThis, 'fetch', async () => {
      requests++
      return new Response(JSON.stringify({ error, stage, reason, upstreamStatus, taskId }), {
        status: upstreamStatus ?? 504, headers: { 'Content-Type': 'application/json' },
      })
    })
    const priorStorage = Object.getOwnPropertyDescriptor(globalThis, 'localStorage')
    Object.defineProperty(globalThis, 'localStorage', {
      value: { getItem: () => null }, configurable: true,
    })
    t.after(() => {
      if (priorStorage) Object.defineProperty(globalThis, 'localStorage', priorStorage)
      else delete globalThis.localStorage
    })
    await assert.rejects(comicflowApi.generateVisual('offline', 's1', 1, 'a'.repeat(64)), (failure) => {
      assert.ok(failure.message.includes(label))
      assert.ok(failure.message.includes('未自动重试'))
      if (upstreamStatus) assert.ok(failure.message.includes(`HTTP ${upstreamStatus}`))
      if (taskId) assert.ok(failure.message.includes(`任务号：${taskId}`))
      assert.equal(failure.detail.stage, stage)
      return true
    })
    assert.equal(requests, 1)
  })
}

for (const attempted of [false, true]) {
  test(`H3 prompt length: explains text expansion attempted=${attempted}`, async (t) => {
    let requests = 0
    t.mock.method(globalThis, 'fetch', async () => {
      requests++
      return new Response(JSON.stringify({
        error: 'VIDEO_PROMPT_TOO_LONG', stage: 'h3_prompt',
        promptCharacters: 8100, maxCharacters: 7000, textExpansionAttempted: attempted,
      }), { status: 400, headers: { 'Content-Type': 'application/json' } })
    })
    const priorStorage = Object.getOwnPropertyDescriptor(globalThis, 'localStorage')
    Object.defineProperty(globalThis, 'localStorage', {
      value: { getItem: () => null }, configurable: true,
    })
    t.after(() => {
      if (priorStorage) Object.defineProperty(globalThis, 'localStorage', priorStorage)
      else delete globalThis.localStorage
    })
    await assert.rejects(comicflowApi.generateVisual('offline', 's2', 1, 'a'.repeat(64)), (failure) => {
      assert.ok(failure.message.includes('8100'))
      assert.ok(failure.message.includes('7000'))
      assert.ok(failure.message.includes('尚未提交 H3'))
      assert.ok(failure.message.includes(attempted ? '文本扩写可能已计费' : '未调用文本模型'))
      assert.ok(failure.message.includes('未自动重试'))
      assert.ok(!failure.message.includes('请精简后再生成'))
      return true
    })
    assert.equal(requests, 1)
  })
}
