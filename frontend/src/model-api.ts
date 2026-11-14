export type ModelCapability = 'text' | 'visual' | 'tts' | 'lipsync'
export type ModelProvider = 'openai-compatible' | 'bailian' | 'openrouter' | 'custom'

export interface ModelApiProfile {
  provider: ModelProvider
  baseUrl: string
  apiKey: string
  model: string
  timeoutMs: number
  enabled: boolean
}

export interface ModelApiConfig {
  profiles: Record<ModelCapability, ModelApiProfile>
  temperature: number
  maxTokens: number
}

export const defaultModelApiConfig: ModelApiConfig = {
  profiles: {
    text: { provider: 'openai-compatible', baseUrl: 'https://api.openai.com/v1', apiKey: '', model: 'gpt-4o-mini', timeoutMs: 120000, enabled: false },
    visual: { provider: 'openai-compatible', baseUrl: 'https://api.openai.com/v1', apiKey: '', model: 'gpt-image-1', timeoutMs: 60000, enabled: false },
    tts: { provider: 'openai-compatible', baseUrl: 'https://api.openai.com/v1', apiKey: '', model: 'gpt-4o-mini-tts', timeoutMs: 30000, enabled: false },
    lipsync: { provider: 'custom', baseUrl: '', apiKey: '', model: 'mock-lipsync-v1', timeoutMs: 30000, enabled: false },
  },
  temperature: 0.7,
  maxTokens: 4096,
}
