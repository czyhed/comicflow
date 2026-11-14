import type { CharacterCard, CharacterPromptFields, CharacterPromptPreview, CharacterPromptPurpose, CharacterSettingField, ImageJob, Project, Script } from '../types'

type Request = <T>(path: string, init?: RequestInit) => Promise<T>

export function createCharacterApi(request: Request) {
  return {
    imageJobs: (projectId: string) => request<{ items: ImageJob[] }>(`/api/projects/${projectId}/image-jobs`),
    requestImageJob: (projectId: string, characterId: string, expectedVersion: number, purpose: 'candidate' | 'views' | 'board' | 'text-board', operationId: string) =>
      request<ImageJob>(`/api/projects/${projectId}/characters/${characterId}/image-jobs`, {
        method: 'POST', body: JSON.stringify({ expectedVersion, purpose, operationId, force: false }),
      }),
    recoverImageJob: (projectId: string, jobId: string) =>
      request<ImageJob>(`/api/projects/${projectId}/image-jobs/${jobId}/recover`, { method: 'POST' }),
    generateCharacterReferenceCandidate: (projectId: string, characterId: string, expectedVersion: number) =>
      request<{ candidate: CharacterCard['referenceImageCandidate']; character: CharacterCard; projectVersion: number }>(
        `/api/projects/${projectId}/characters/${characterId}/reference-candidate`, {
          method: 'POST', body: JSON.stringify({ expectedVersion }),
        }),
    approveCharacterReferenceCandidate: (projectId: string, characterId: string, candidateId: string, expectedVersion: number) =>
      request<{ character: CharacterCard; projectVersion: number }>(
        `/api/projects/${projectId}/characters/${characterId}/reference-candidate/approve`, {
          method: 'POST', body: JSON.stringify({ candidateId, expectedVersion }),
        }),
    approveCharacterReferenceBoard: (projectId: string, characterId: string, candidateId: string, expectedVersion: number) =>
      request<{ character: CharacterCard; projectVersion: number }>(
        `/api/projects/${projectId}/characters/${characterId}/reference-board/approve`, {
          method: 'POST', body: JSON.stringify({ candidateId, expectedVersion }),
        }),
    generateCharacterReferenceViews: (projectId: string, characterId: string, expectedVersion: number, force = false) =>
      request<{ character: CharacterCard; views: NonNullable<CharacterCard['referenceViews']>; projectVersion: number; reused: boolean }>(
        `/api/projects/${projectId}/characters/${characterId}/reference-views`, {
          method: 'POST', body: JSON.stringify({ expectedVersion, force }),
        }),
    projectCharacters: (projectId: string) => request<CharacterCard[]>(`/api/projects/${projectId}/characters`),
    previewCharacterPrompt: (projectId: string, payload: { fields: CharacterPromptFields; instructions: string; expectedVersion: number; characterId?: string; expectedRevision: number; purpose?: CharacterPromptPurpose; outputFields?: CharacterSettingField[] }) =>
      request<CharacterPromptPreview>(`/api/projects/${projectId}/characters/prompt-preview`, {
        method: 'POST', body: JSON.stringify(payload),
      }),
    syncProjectCharacters: (projectId: string, expectedVersion: number) =>
      request<{ project: Project; script: Script }>(`/api/projects/${projectId}/characters/sync`, {
        method: 'POST', body: JSON.stringify({ expectedVersion }),
      }),
    saveProjectCharacter: (projectId: string, card: Omit<CharacterCard, 'id'>, characterId?: string, expectedVersion?: number) =>
      request<CharacterCard>(`/api/projects/${projectId}/characters${characterId ? `/${characterId}` : ''}`, {
        method: characterId ? 'PATCH' : 'POST', body: JSON.stringify({
          name: card.name, appearance: card.appearance, clothing: card.clothing,
          personality: card.personality, voice: card.voice,
          referenceImagePrompt: card.referenceImagePrompt ?? '',
          ...(characterId ? { expectedRevision: card.revision ?? 0 } : {}),
          ...(expectedVersion === undefined ? {} : { expectedVersion }),
        }),
      }),
    assignShotCharacters: (projectId: string, shotId: string, characterIds: string[], expectedVersion: number) =>
      request<{ characterIds: string[]; projectVersion: number }>(`/api/projects/${projectId}/script/shots/${shotId}/characters`, {
        method: 'PUT', body: JSON.stringify({ characterIds, expectedVersion }),
      }),
  }
}
