import { readFile } from 'node:fs/promises'
import ts from 'typescript'

function moduleUrl(source) {
  const compiled = ts.transpileModule(source, {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
  }).outputText
  return `data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`
}

export async function loadApiClient() {
  const operationId = moduleUrl(await readFile(new URL('../../src/operation-id.ts', import.meta.url), 'utf8'))
  const textStream = moduleUrl(await readFile(new URL('../../src/api/textStream.ts', import.meta.url), 'utf8'))
  const errors = await readFile(new URL('../../src/visual-preflight.ts', import.meta.url), 'utf8')
  const video = await readFile(new URL('../../src/api/video.ts', import.meta.url), 'utf8')
  const characters = await readFile(new URL('../../src/api/characters.ts', import.meta.url), 'utf8')
  const storyScripts = await readFile(new URL('../../src/api/storyScripts.ts', import.meta.url), 'utf8')
  const composition = await readFile(new URL('../../src/api/composition.ts', import.meta.url), 'utf8')
  const audio = await readFile(new URL('../../src/api/audio.ts', import.meta.url), 'utf8')
  const source = await readFile(new URL('../../src/api/client.ts', import.meta.url), 'utf8')
  return import(moduleUrl(source.replace('import.meta.env.VITE_API_ROOT', "''")
    .replace("'./textStream'", JSON.stringify(textStream))
    .replace("'./audio'", JSON.stringify(moduleUrl(audio)))
    .replace("'./composition'", JSON.stringify(moduleUrl(composition.replace("'../operation-id'", JSON.stringify(operationId)))))
    .replace("'./storyScripts'", JSON.stringify(moduleUrl(storyScripts)))
    .replace("'./characters'", JSON.stringify(moduleUrl(characters)))
    .replace("'../visual-preflight'", JSON.stringify(moduleUrl(errors)))
    .replace("'./video'", JSON.stringify(moduleUrl(video.replace("'../operation-id'", JSON.stringify(operationId)).replace("'../visual-preflight'", JSON.stringify(moduleUrl(errors))))))))
}
