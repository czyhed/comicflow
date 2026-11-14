import { useQuery } from '@tanstack/react-query'
import { useEffect } from 'react'
import { comicflowApi } from '../api/client'
import { AppShell } from '../components/AppShell'
import { ErrorBoundary } from '../components/ErrorBoundary'
import { AudioWorkspace } from '../features/audio/AudioWorkspace'
import { CharacterWorkspace } from '../features/characters/CharacterWorkspace'
import { CreateWorkspace } from '../features/create/CreateWorkspace'
import { ExportWorkspace } from '../features/export/ExportWorkspace'
import { ScriptWorkspace } from '../features/script/ScriptWorkspace'
import { StoryboardWorkspace } from '../features/storyboard/StoryboardWorkspace'
import { VisualWorkspace } from '../features/visuals/VisualWorkspace'
import { VideoResourcesWorkspace } from '../features/resources/VideoResourcesWorkspace'
import { useWorkspace } from '../stores/workspace'
import type { Snapshot } from '../types'

export function App() {
  const { activeModule, projectId, clearProject, navigationRevision } = useWorkspace()
  const snapshot = useQuery({
    queryKey: ['snapshot', projectId],
    queryFn: () => comicflowApi.snapshot(projectId!),
    enabled: Boolean(projectId),
    // A missing project is terminal for this browser session. Retrying it
    // only produces duplicate 404s while the effect below clears local state.
    retry: false,
    refetchInterval: (query) => {
      if (!projectId || query.state.status !== 'success') return false
      const data = query.state.data as Snapshot | undefined
      const session = data?.project?.generationSession
      const jobs = data?.jobs ?? []
      return session?.status === 'running' || jobs.some((job) => job.status === 'queued' || job.status === 'running')
        ? 1000
        : false
    },
  })
  useEffect(() => {
    if (!snapshot.error) return
    const message = snapshot.error instanceof Error ? snapshot.error.message : ''
    if (message === 'PROJECT_NOT_FOUND' || message === 'HTTP_404') clearProject()
  }, [snapshot.error, clearProject])
  const workspace = {
    create: <CreateWorkspace snapshot={snapshot.data} />,
    script: <ScriptWorkspace snapshot={snapshot.data} />,
    storyboard: <StoryboardWorkspace snapshot={snapshot.data} />,
    characters: <CharacterWorkspace snapshot={snapshot.data} />,
    visuals: <VisualWorkspace snapshot={snapshot.data} />,
    audio: <AudioWorkspace snapshot={snapshot.data} />,
    export: <ExportWorkspace snapshot={snapshot.data} />,
    resources: <VideoResourcesWorkspace snapshot={snapshot.data} />,
  }[activeModule]

  return (
    <AppShell snapshot={snapshot.data} loading={Boolean(projectId) && snapshot.isPending}
      loadError={snapshot.isError} onReload={() => { void snapshot.refetch() }}>
      <ErrorBoundary key={`${navigationRevision}:${activeModule}`}>{workspace}</ErrorBoundary>
    </AppShell>
  )
}
