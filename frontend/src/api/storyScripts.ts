import type { TextProgress } from './textStream'
import type { GenerationSession, Project, Script, ScriptPreview } from '../types'

type Request = <T>(path: string, init?: RequestInit, onProgress?: (event: TextProgress) => void) => Promise<T>

export function createStoryScriptApi(request: Request) {
  return {
    generateScript: (projectId: string) =>
      request<{ project: Project; script: Script }>(`/api/projects/${projectId}/script`, {
        method: 'POST',
        body: '{}',
      }),
    generateStoryText: (projectId: string, onProgress?: (event: TextProgress) => void) =>
      request<{ project: Project; storyText: string }>(`/api/projects/${projectId}/story`, {
        method: 'POST',
        body: '{}',
      }, onProgress),
    updateStoryText: (projectId: string, storyText: string, expectedVersion: number) =>
      request<{ project: Project; storyText: string }>(`/api/projects/${projectId}/story`, {
        method: 'PATCH',
        body: JSON.stringify({ storyText, expectedVersion }),
      }),
    splitScript: (projectId: string) =>
      request<{ project: Project; script: Script }>(`/api/projects/${projectId}/script/split`, {
        method: 'POST',
        body: '{}',
      }),
    previewScript: (projectId: string, onProgress?: (event: TextProgress) => void) =>
      request<ScriptPreview>(
        `/api/projects/${projectId}/script/preview`, { method: 'POST', body: '{}' }, onProgress,
      ),
    commitScriptPreview: (projectId: string, preview: ScriptPreview) =>
      request<{ project: Project; script: Script }>(`/api/projects/${projectId}/script/preview`, {
        method: 'PUT',
        body: JSON.stringify({ script: preview.script, expectedVersion: preview.expectedVersion }),
      }),
    askGuidedQuestion: (projectId: string) =>
      request<{ guided: NonNullable<GenerationSession['guided']> }>(
        `/api/projects/${projectId}/script/guidance`,
        { method: 'POST', body: '{}' },
      ),
    answerGuidedQuestion: (projectId: string, answer: string) =>
      request<{ guided: NonNullable<GenerationSession['guided']> }>(
        `/api/projects/${projectId}/script/guidance/answer`,
        { method: 'POST', body: JSON.stringify({ answer }) },
      ),
    skipGuidedQuestion: (projectId: string) =>
      request<{ guided: NonNullable<GenerationSession['guided']> }>(
        `/api/projects/${projectId}/script/guidance/skip`,
        { method: 'POST', body: '{}' },
      ),
    generateDetailedScript: (projectId: string) =>
      request<{ project: Project; script: Script }>(
        `/api/projects/${projectId}/script/detail`,
        { method: 'POST', body: '{}' },
      ),
    updateScript: (projectId: string, script: Script, expectedVersion: number) =>
      request<{ project: Project; script: Script }>(`/api/projects/${projectId}/script`, {
        method: 'PATCH',
        body: JSON.stringify({ script, expectedVersion }),
      }),
    confirmScript: (projectId: string, expectedVersion: number) =>
      request<{ project: Project; script: Script }>(`/api/projects/${projectId}/script/confirm`, {
        method: 'POST',
        body: JSON.stringify({ expectedVersion }),
      }),
  }
}
