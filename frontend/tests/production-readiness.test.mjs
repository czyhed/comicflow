import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'

const source = await readFile(new URL('../src/production-readiness.ts', import.meta.url), 'utf8')
const compiled = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
}).outputText
const { readProductionReadiness } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`)

function snapshot(provider, valid = true) {
  return {
    script: { shots: [{ id: 's1', dialogue: '别走。', narration: '' }] },
    visualAssets: [{ id: 'v1', shotId: 's1', provider, mediaType: 'video', valid }],
    audioAssets: [],
  }
}

test('H3 original soundtrack does not require a separate voice asset to request composition', () => {
  const result = readProductionReadiness(snapshot('minimax'))
  assert.equal(result.composable, true)
  assert.deepEqual(result.missingAudio, [])
  assert.equal(result.audioNeeded, 0)
  assert.equal(result.nativeAudioShots.length, 1)
})

test('other providers still require explicit voice preparation', () => {
  const result = readProductionReadiness(snapshot('bailian'))
  assert.equal(result.composable, false)
  assert.equal(result.missingAudio.length, 1)
  assert.equal(result.audioNeeded, 1)
})

test('an obsolete H3 video cannot qualify its replacement for native audio', () => {
  const data = snapshot('minimax', false)
  data.visualAssets.push({ id: 'v2', shotId: 's1', provider: 'bailian', mediaType: 'video', valid: true })
  const result = readProductionReadiness(data)
  assert.equal(result.composable, false)
  assert.equal(result.nativeAudioShots.length, 0)
})
