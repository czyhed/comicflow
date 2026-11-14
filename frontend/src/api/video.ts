import { createOperationId } from '../operation-id'
import type { VideoJob, VisualPreflight } from '../types'
import { preflightError } from '../visual-preflight'

type Request = <T>(path: string, init?: RequestInit) => Promise<T>
type VideoCandidate = { asset: Record<string, unknown>; projectVersion: number; jobId: string; awaitingAdoption: boolean }

export function createVideoApi(request: Request) {
  const api = {
  previewVisual: (projectId: string, shotId: string, expectedVersion: number, continuityMode?: 'auto' | 'previous-tail') =>
    request<VisualPreflight>(`/api/projects/${projectId}/shots/${shotId}/visual/preflight`, {
      method: 'POST', body: JSON.stringify({ expectedVersion, ...(continuityMode && continuityMode !== 'auto' ? { continuityMode } : {}) }),
    }).then(data => {
      if (!data || typeof data.ready !== 'boolean' || !Array.isArray(data.references) || !Array.isArray(data.errors)) {
        throw new Error('生成准备接口返回无效，请确认前后端版本一致')
      }
      return data
    }),
  generateVisual: async (projectId: string, shotId: string, expectedVersion: number, preflightFingerprint?: string) => {
    if (!preflightFingerprint) {
      const prepared = await api.previewVisual(projectId, shotId, expectedVersion)
      if (!prepared.ready || !prepared.fingerprint) throw new Error(preflightError(prepared.errors[0] ?? 'PREFLIGHT_REQUIRED'))
      preflightFingerprint = prepared.fingerprint
    }
    return request<VideoCandidate>(`/api/projects/${projectId}/shots/${shotId}/visual`, {
      method: 'POST',
      body: JSON.stringify({ expectedVersion, preflightFingerprint }),
    })
  },
  videoJobs: (projectId: string) => request<{ items: VideoJob[] }>(`/api/projects/${projectId}/video-jobs`).then(data => {
    if (!Array.isArray(data.items)) throw new Error('任务列表读取失败，请确认后端已更新并完成数据库迁移')
    return data.items
  }),
  videoJob: (projectId: string, jobId: string, signal?: AbortSignal) =>
    request<VideoJob>(`/api/projects/${projectId}/video-jobs/${jobId}`, { signal }),
  queueVideo: async (projectId: string, shotId: string, expectedVersion: number, preflightFingerprint?: string, signal?: AbortSignal, continuityMode?: 'auto' | 'previous-tail') => {
    if (!preflightFingerprint) {
      const prepared = await api.previewVisual(projectId, shotId, expectedVersion, continuityMode)
      if (!prepared.ready || !prepared.fingerprint) throw new Error(preflightError(prepared.errors[0] ?? 'PREFLIGHT_REQUIRED'))
      preflightFingerprint = prepared.fingerprint
    }
    signal?.throwIfAborted()
    const operationId = createOperationId()
    return request<VideoJob>(`/api/projects/${projectId}/shots/${shotId}/video-jobs`, {
      method: 'POST', signal, body: JSON.stringify({ expectedVersion, preflightFingerprint, operationId, ...(continuityMode && continuityMode !== 'auto' ? { continuityMode } : {}) }),
    })
  },
  recoverVideo: (projectId: string, jobId: string, taskId?: string) =>
    request<VideoJob>(`/api/projects/${projectId}/video-jobs/${jobId}/recover`, {
      method: 'POST', body: JSON.stringify({ taskId: taskId || null }),
    }),
  adoptVideo: (projectId: string, jobId: string) =>
    request<VideoJob>(`/api/projects/${projectId}/video-jobs/${jobId}/adopt`, {
      method: 'POST',
    }),
  regenerateShot: (projectId: string, shotId: string, scope: 'visual' | 'audio' | 'lipsync' | 'shot', expectedVersion: number) =>
    request<{ scope: string; timeline?: Record<string, unknown>; projectVersion: number; jobId?: string; awaitingAdoption?: boolean }>(`/api/projects/${projectId}/shots/${shotId}/regenerate`, {
      method: 'POST',
      body: JSON.stringify({ scope, expectedVersion }),
    }),
  }
  return api
}
