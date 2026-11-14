export type TextProgress =
  | { type: 'phase'; phase: string; label?: string }
  | { type: 'delta'; delta: string }

/** Consume the same POST response; EOF without a terminal event is never success. */
export async function readTextStream(response: Response, onProgress: (event: TextProgress) => void): Promise<Response> {
  const reader = response.body?.getReader()
  if (!reader) throw new Error('生成连接没有返回内容，未自动重试。请先检查项目中的已保存结果。')
  const decoder = new TextDecoder()
  let buffer = ''
  let data: string[] = []
  try {
    while (true) {
      const { value, done } = await reader.read()
      buffer += decoder.decode(value, { stream: !done })
      let index: number
      while ((index = buffer.indexOf('\n')) >= 0) {
        const line = buffer.slice(0, index).replace(/\r$/, '')
        buffer = buffer.slice(index + 1)
        if (line.startsWith('data:')) data.push(line.slice(5).trimStart())
        if (line !== '' || data.length === 0) continue
        const event = JSON.parse(data.join('\n'))
        data = []
        if (event.type === 'result') return Response.json(event.result)
        if (event.type === 'error') return Response.json(event.error, { status: 502 })
        if (event.type === 'delta' && typeof event.delta === 'string') onProgress(event)
        if (event.type === 'phase' && typeof event.phase === 'string') onProgress(event)
      }
      if (done) throw new Error('STREAM_INCOMPLETE')
    }
  } catch {
    throw new Error('生成连接中断，未自动重试。已收到的内容尚未确认完成，请先检查项目中的已保存结果。')
  } finally {
    await reader.cancel().catch(() => undefined)
    reader.releaseLock()
  }
}
