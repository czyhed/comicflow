import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'
import ts from 'typescript'

const toModule = async (path, replace = {}) => {
  let code = ts.transpileModule(await readFile(new URL(path, import.meta.url), 'utf8'), {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
  }).outputText
  for (const [from, to] of Object.entries(replace)) code = code.replace(from, to)
  return `data:text/javascript;base64,${Buffer.from(code).toString('base64')}`
}
// workflow-steps.ts imports production-readiness.ts; point that import at its transpiled copy.
const readiness = await toModule('../src/production-readiness.ts')
const { workflowSteps } = await import(await toModule('../src/workflow-steps.ts', { './production-readiness': readiness }))

const shot = (id, extra = {}) => ({ id, dialogue: '你好', narration: '', ...extra })
const base = (overrides = {}) => ({
  project: { id: 'p', stage: 'storyboard-ready', generatedStoryText: '故事' },
  script: { title: 't', scenes: [], shots: [shot('s1'), shot('s2')] },
  visualAssets: [], audioAssets: [], jobs: [], ...overrides,
})

test('no project shows no progress', () => {
  assert.deepEqual(workflowSteps(undefined), {})
})

test('unconfirmed script is marked as pending and later steps stay quiet', () => {
  const steps = workflowSteps(base({ project: { id: 'p', stage: 'awaiting-confirmation' } }))
  assert.equal(steps.create.done, true)
  assert.deepEqual(steps.script, { done: false, hint: '待确认' })
  assert.equal(steps.visuals, undefined)
})

test('visual progress counts adopted shots; H3 native audio needs no separate voice', () => {
  const steps = workflowSteps(base({ visualAssets: [
    { shotId: 's1', valid: true, provider: 'minimax', mediaType: 'video' },
  ] }))
  assert.equal(steps.script.done, true)
  assert.deepEqual(steps.visuals, { done: false, hint: '1/2' })
  const all = workflowSteps(base({ visualAssets: ['s1', 's2'].map(shotId => ({ shotId, valid: true, provider: 'minimax', mediaType: 'video' })) }))
  assert.equal(all.visuals.done, true)
  assert.deepEqual(all.audio, { done: true })
})

test('export is done only with a manifest', () => {
  assert.equal(workflowSteps(base()).export.done, false)
  assert.equal(workflowSteps(base({ exportManifest: { files: ['video.mp4'] } })).export.done, true)
})
