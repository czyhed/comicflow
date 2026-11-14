import { createServer, type ServerResponse } from 'node:http'
import type { AddressInfo } from 'node:net'
import type { Page } from '@playwright/test'

/** A real local streaming response, held open until the UI has observed its delta. */
export async function textStreamServer(page: Page, path: string, delta: string) {
  let response: ServerResponse | undefined
  let calls = 0
  const server = createServer((request, res) => {
    res.setHeader('Access-Control-Allow-Origin', '*')
    res.setHeader('Access-Control-Allow-Headers', '*')
    if (request.method === 'OPTIONS') { res.end(); return }
    calls++
    response = res
    res.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' })
    res.write(`data: ${JSON.stringify({ type: 'delta', delta })}\n\n`)
  })
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve))
  const port = (server.address() as AddressInfo).port
  await page.route(path, route => route.continue({ url: `http://127.0.0.1:${port}/stream` }))
  return {
    calls: () => calls,
    finish: (event: Record<string, unknown>) => response!.end(`data: ${JSON.stringify(event)}\n\n`),
    close: async () => {
      server.closeAllConnections()
      await new Promise<void>(resolve => server.close(() => resolve()))
    },
  }
}
