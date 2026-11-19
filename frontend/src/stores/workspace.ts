import { create } from 'zustand'

export const modules = ['create', 'script', 'storyboard', 'characters', 'visuals', 'audio', 'export', 'resources'] as const
export type WorkspaceModule = (typeof modules)[number]

interface WorkspaceState {
  activeModule: WorkspaceModule
  projectId: string | null
  selectedShotId: string | null
  navigationRevision: number
  openExistingProject: (projectId: string, module: WorkspaceModule) => void
  setActiveModule: (activeModule: WorkspaceModule) => void
  setProjectId: (projectId: string) => void
  clearProject: () => void
  setSelectedShotId: (selectedShotId: string) => void
}

export const useWorkspace = create<WorkspaceState>((set) => ({
  activeModule: 'create',
  projectId: localStorage.getItem('comicflow-project-id'),
  selectedShotId: null,
  navigationRevision: 0,
  openExistingProject: (projectId, activeModule) => {
    localStorage.setItem('comicflow-project-id', projectId)
    // Reset editor drafts only on explicit project navigation. Creating a
    // project must keep its in-flight story/preview component alive.
    set(state => ({ projectId, activeModule, selectedShotId: null,
      navigationRevision: state.navigationRevision + 1 }))
  },
  setActiveModule: (activeModule) => set({ activeModule }),
  setProjectId: (projectId) => {
    localStorage.setItem('comicflow-project-id', projectId)
    set({ projectId, selectedShotId: null })
  },
  clearProject: () => {
    localStorage.removeItem('comicflow-project-id')
    set({ projectId: null, activeModule: 'create', selectedShotId: null })
  },
  setSelectedShotId: (selectedShotId) => set({ selectedShotId }),
}))
