import { createOperationId } from '../operation-id'

type Request = <T>(path: string, init?: RequestInit) => Promise<T>

export function createCompositionApi(request: Request) {
  return {
    requestComposition: (projectId: string, expectedVersion: number, shotIds?: string[], shotTrims?: Record<string, { inSec: number; outSec: number }>) =>
      request<{ id: string; status: string }>(`/api/projects/${projectId}/composition`, {
        method: 'POST',
        body: JSON.stringify({ expectedVersion, idempotencyKey: createOperationId(), ...(shotIds ? { shotIds } : {}), ...(shotTrims && Object.keys(shotTrims).length ? { shotTrims } : {}) }),
      }),
    exportPackage: (projectId: string, jobId?: string) =>
      request<{ files: string[]; format: string; projectId: string; downloadUrl?: string; downloads?: Record<string, string>; scope?: string; shotIds?: string[]; jobId?: string }>(
        `/api/projects/${projectId}/export${jobId ? `?job_id=${encodeURIComponent(jobId)}` : ''}`,
      ),
  }
}
