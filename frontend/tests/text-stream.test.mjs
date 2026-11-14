import assert from 'node:assert/strict'
import { test } from 'node:test'
import { loadApiClient } from './helpers/load-api-client.mjs'

const { comicflowApi } = await loadApiClient()
globalThis.localStorage = { getItem: () => 'offline-user' }

test('one POST displays UTF8 deltas before final result, preserving authorization', async () => {
  let controller
  let calls = 0
  let finished = false
  globalThis.fetch = async (_url, init) => {
    calls++
    assert.equal(init.headers.Accept, 'text/event-stream')
    assert.equal(init.headers['X-User-Id'], 'offline-user')
    return new Response(new ReadableStream({ start(value) { controller = value } }),
      { headers: { 'Content-Type': 'text/event-stream' } })
  }
  const received = []
  const pending = comicflowApi.previewScript('p', event => received.push(event))
    .then(value => { finished = true; return value })
  await new Promise(resolve => setTimeout(resolve, 0))
  const bytes = new TextEncoder().encode('data: {"type":"delta","delta":"雨夜车站"}\r\n\r\n')
  for (const byte of bytes) controller.enqueue(new Uint8Array([byte]))
  await new Promise(resolve => setTimeout(resolve, 0))
  assert.deepEqual(received, [{ type: 'delta', delta: '雨夜车站' }])
  assert.equal(finished, false)
  controller.enqueue(new TextEncoder().encode('data: {"type":"result","result":{"expectedVersion":2}}\n\n'))
  assert.deepEqual(await pending, { expectedVersion: 2 })
  assert.equal(calls, 1)
})

test('truncated stream is not accepted or automatically resubmitted', async () => {
  let calls = 0
  globalThis.fetch = async () => {
    calls++
    return new Response('data: {"type":"delta","delta":"部分内容"}\n\n',
      { headers: { 'Content-Type': 'text/event-stream' } })
  }
  await assert.rejects(comicflowApi.previewScript('p', () => {}), /连接中断.*未自动重试/)
  assert.equal(calls, 1)
})

test('streamed provider refusal retains existing actionable error mapping', async () => {
  globalThis.fetch = async () => new Response('data: ' + JSON.stringify({
    type: 'error', error: { error: 'PROVIDER_INVALID_RESPONSE', stage: 'script_split', reason: 'output_truncated' },
  }) + '\n\n', { headers: { 'Content-Type': 'text/event-stream' } })
  await assert.rejects(comicflowApi.previewScript('p', () => {}), /未自动重试/)
})

test('an older server JSON response works without a second POST', async () => {
  let calls = 0
  globalThis.fetch = async () => { calls++; return Response.json({ storyText: '完整故事' }) }
  assert.deepEqual(await comicflowApi.generateStoryText('p', () => {}), { storyText: '完整故事' })
  assert.equal(calls, 1)
})

test('HTTP composition works without randomUUID and generates distinct UUIDs', async () => {
  const descriptor = Object.getOwnPropertyDescriptor(globalThis.crypto, 'randomUUID')
  Object.defineProperty(globalThis.crypto, 'randomUUID', { value: undefined, configurable: true })
  const ids = []
  globalThis.fetch = async (_url, init) => {
    ids.push(JSON.parse(init.body).idempotencyKey)
    return Response.json({ id: 'job', status: 'queued' })
  }
  try {
    await comicflowApi.requestComposition('p', 2)
    await comicflowApi.requestComposition('p', 2)
    assert.notEqual(ids[0], ids[1])
    for (const id of ids) assert.match(id, /^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/)
  } finally {
    if (descriptor) Object.defineProperty(globalThis.crypto, 'randomUUID', descriptor)
    else delete globalThis.crypto.randomUUID
  }
})
