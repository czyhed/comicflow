type Request = <T>(path: string, init?: RequestInit) => Promise<T>

export function createAudioApi(request: Request) {
  return {
    generateAudio: (projectId: string, shotId: string, expectedVersion: number) =>
      request<{ timeline: Record<string, unknown>; projectVersion: number }>(`/api/projects/${projectId}/shots/${shotId}/audio`, {
        method: 'POST',
        body: JSON.stringify({ expectedVersion }),
      }),
  }
}
