import { request } from './client'

export interface ModelConnection {
  id: string
  name: string
  baseUrl: string
  configured: boolean
}
export interface RegistryModel {
  id: string
  name: string
  connectionId: string
  model: string
  protocol: string
  enabled: boolean
  config: Record<string, unknown>
}
export interface ModelCatalog {
  revision: number
  scope: string
  connections: ModelConnection[]
  models: RegistryModel[]
  bindings: Record<string, string>
  usages: Record<string, string>
  templates: Record<string, { name: string; usages: string[]; defaults: Record<string, unknown> }>
}
export interface ConnectionTestResult {
  status: 'ok' | 'partial' | 'failed'
  scope: 'text' | 'address'
  message: string
  model?: string
  upstreamStatus?: number
  parameter?: string
  elapsedMs: number
  revision: number
}
const root = '/api/model-registry'
export const modelRegistry = {
  read: async () => {
    const data = await request<ModelCatalog>(root)
    if (!Array.isArray(data.connections) || !Array.isArray(data.models) || !data.templates || !data.usages || !data.bindings || !Number.isInteger(data.revision)) {
      throw new Error('模型库响应不完整，请核对后端版本和数据库迁移。')
    }
    return data
  },
  save: (kind: 'connections' | 'models', id: string | undefined, payload: unknown) =>
    request<ModelCatalog>(`${root}/${kind}${id ? `/${encodeURIComponent(id)}` : ''}`, {
      method: id ? 'PUT' : 'POST', body: JSON.stringify(payload),
    }),
  remove: (kind: 'connections' | 'models', id: string, revision: number) =>
    request<ModelCatalog>(`${root}/${kind}/${encodeURIComponent(id)}?revision=${revision}`, { method: 'DELETE' }),
  bind: (revision: number, bindings: Record<string, string | null>) =>
    request<ModelCatalog>(`${root}/bindings`, { method: 'PUT', body: JSON.stringify({ revision, bindings }) }),
  import: (revision: number) => request<ModelCatalog>(`${root}/import-legacy`, {
    method: 'POST', body: JSON.stringify({ revision }),
  }),
  preview: (id: string) => request<Record<string, unknown>>(`${root}/models/${encodeURIComponent(id)}/preview`, { method: 'POST' }),
  testConnection: (id: string, revision: number, modelId: string | null) =>
    request<ConnectionTestResult>(`${root}/connections/${encodeURIComponent(id)}/test`, {
      method: 'POST', body: JSON.stringify({ revision, modelId }),
    }),
}
