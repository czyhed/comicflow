import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'

// script-budget.ts only has a type import, which transpileModule drops.
const source = await readFile(new URL('../src/features/script/script-budget.ts', import.meta.url), 'utf8')
const compiled = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
}).outputText
const { speechBudget, spokenLength, hasChainedCameraMove } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`)

test('speech limit leaves one second for action at four characters per second', () => {
  assert.equal(speechBudget({ dialogue: '', narration: '', durationSec: 5 }).limit, 16)
  assert.equal(speechBudget({ dialogue: '', narration: '', durationSec: 8 }).limit, 28)
  assert.equal(speechBudget({ dialogue: '', narration: '', durationSec: 1 }).limit, 0)
})

test('status reflects combined dialogue and narration', () => {
  assert.equal(speechBudget({ dialogue: '', narration: '', durationSec: 5 }).status, 'silent')
  assert.equal(speechBudget({ dialogue: '有人吗？', narration: '', durationSec: 5 }).status, 'ok')
  assert.equal(speechBudget({ dialogue: '一二三四五六七', narration: '八九十十一十二', durationSec: 5 }).status, 'near')
  const over = speechBudget({ dialogue: '林夏：有人吗？', narration: '那天夜里，雨下得格外大，整条街只剩这家便利店还亮着灯。', durationSec: 5 })
  assert.equal(over.status, 'over')
  assert.equal(over.used, spokenLength('林夏：有人吗？') + spokenLength('那天夜里，雨下得格外大，整条街只剩这家便利店还亮着灯。'))
})

test('punctuation is not counted as spoken characters', () => {
  assert.equal(spokenLength('“你，来了？”'), 3)
  assert.equal(spokenLength(undefined), 0)
})

test('chained camera moves are flagged only on short shots', () => {
  const move = '手持跟拍，从站台快速推进到车门，随后稳定在车厢内'
  assert.equal(hasChainedCameraMove({ cameraMovement: move, durationSec: 5 }), true)
  assert.equal(hasChainedCameraMove({ cameraMovement: move, durationSec: 8 }), false)
  assert.equal(hasChainedCameraMove({ cameraMovement: '缓慢推近', durationSec: 5 }), false)
  assert.equal(hasChainedCameraMove({ durationSec: 5 }), false)
})
