import { AudioLines, BookOpenText, Check, Clapperboard, Download, FolderOpen, LayoutDashboard, Settings2, Sparkles, Users } from 'lucide-react'
import { workflowSteps, type StepModule } from '../workflow-steps'
import { useEffect, useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { comicflowApi } from '../api/client'
import { type WorkspaceModule, useWorkspace } from '../stores/workspace'
import type { Snapshot } from '../types'
import { ModelApiSettings } from './ModelApiSettings'
import { ClaimProjectDialog } from './ClaimProjectDialog'
import { ProjectPicker, projectTitle } from './ProjectPicker'

const navigation: Array<{ id: WorkspaceModule; label: string; detail: string; icon: typeof Sparkles }> = [
  { id: 'create', label: '创建', detail: '故事与参数', icon: Sparkles },
  { id: 'script', label: '剧本', detail: '场景与对白', icon: BookOpenText },
  { id: 'storyboard', label: '分镜', detail: '镜头编排', icon: LayoutDashboard },
  { id: 'characters', label: '角色', detail: '角色一致性', icon: Users },
  { id: 'visuals', label: '画面', detail: '动态镜头', icon: Clapperboard },
  { id: 'audio', label: '声音', detail: '原声与字幕', icon: AudioLines },
  { id: 'export', label: '导出', detail: '预览与交付', icon: Download },
  { id: 'resources', label: '资源', detail: '历史视频', icon: FolderOpen },
]

const stageLabels: Record<string, string> = {
  created: '待创作', story: '故事准备', 'story-generating': '故事生成中',
  'story-generated': '故事已保存', 'script-generating': '剧本拆分中',
  'script-completed': '剧本待确认', 'awaiting-confirmation': '剧本待确认',
  'storyboard-ready': '剧本已确认', visuals: '镜头制作', audio: '声音准备',
  'assets-ready': '素材已就绪', composition: '成片合成', exported: '成片已就绪', completed: '制作完成',
}
const sessionLabels: Record<string, string> = {
  ready: '等待操作', running: '处理中', paused: '已暂停', completed: '已完成',
  cancelled: '已取消', 'waiting-retry': '失败待处理', failed: '失败待处理',
}

export function AppShell({ children, snapshot, loading = false, loadError = false, onReload }: {
  children: ReactNode; snapshot?: Snapshot; loading?: boolean; loadError?: boolean; onReload?: () => void
}) {
  const { activeModule, setActiveModule, setSelectedShotId } = useWorkspace()
  const [modelOpen, setModelOpen] = useState(false)
  const [claimOpen, setClaimOpen] = useState(false)
  const [projectOpen, setProjectOpen] = useState(false)
  const [credits, setCredits] = useState<number | null>(null)
  const queryClient = useQueryClient()
  const automatic = snapshot?.project?.input?.mode === 'automatic'
  const session = useQuery({
    queryKey: ['generation-session', snapshot?.project.id],
    queryFn: () => comicflowApi.generationSession(snapshot!.project.id),
    enabled: automatic,
    retry: false,
    refetchInterval: query => query.state.data?.status === 'running' ? 1000 : false,
  })
  const refresh = () => Promise.all([
    queryClient.invalidateQueries({ queryKey: ['generation-session'] }),
    queryClient.invalidateQueries({ queryKey: ['snapshot'] }),
  ])
  const sessionAction = useMutation({
    mutationFn: (action: 'pause' | 'resume' | 'cancel' | 'retry') => comicflowApi.updateGenerationSession(snapshot!.project.id, action),
    onSuccess: refresh,
  })
  const advance = useMutation({ mutationFn: () => comicflowApi.advanceGenerationSession(snapshot!.project.id), onSuccess: refresh })
  const stageNow = session.data?.stage ?? snapshot?.project?.stage ?? ''
  const beforeConfirm = ['story', 'story-generating', 'story-generated', 'script-generating', 'script-completed', 'awaiting-confirmation'].includes(stageNow)
  const sessionBusy = sessionAction.isPending || advance.isPending
  const actionError = sessionAction.error ?? advance.error
  const stopped = session.data?.status === 'cancelled' || session.data?.status === 'completed'
  const waitingAdoption = session.data?.status === 'paused' && session.data.pauseReason === 'video-awaiting-adoption'
  const waitingAssets = snapshot?.visualAssets?.filter(asset => asset.shotId === session.data?.waitingShotId) ?? []
  const canResume = !waitingAdoption || Boolean(waitingAssets.at(-1)?.valid)
  const composing = snapshot?.jobs.some(job => job.type === 'composition' && ['queued', 'running'].includes(job.status))
  const productionStatus = composing ? '成片合成中' : snapshot?.exportManifest ? '成片已就绪'
    : stageLabels[snapshot?.project.stage ?? ''] ?? '项目已保存'
  useEffect(() => { setCredits(null) }, [snapshot?.project.id])
  useEffect(() => {
    const workspace = document.querySelector('.workspace')
    const top = workspace ? workspace.getBoundingClientRect().top + window.scrollY - 8 : 0
    window.scrollTo({ top: Math.max(0, top), behavior: 'smooth' })
  }, [activeModule])
  const steps = workflowSteps(snapshot)
  const nav = <div className="module-nav" aria-label="工作区导航">
    {navigation.map(({ id, label, detail, icon: Icon }) => {
      const step = id === 'resources' ? undefined : steps[id as StepModule]
      const classes = [activeModule === id ? 'active' : '', step?.done ? 'step-done' : '', id === 'resources' ? 'nav-aside' : ''].filter(Boolean).join(' ')
      // aria-label stays the bare module name; progress is decorative and repeated in title.
      return <button key={id} title={`${label} · ${detail}${step?.hint ? ` · ${step.hint}` : step?.done ? ' · 已完成' : ''}`} aria-label={label}
        aria-pressed={activeModule === id} className={classes} onClick={() => setActiveModule(id)}>
        <Icon size={15} /><span>{label}</span>
        {step?.done && !step.hint ? <Check className="step-check" size={12} aria-hidden="true" />
          : step?.hint ? <small className="step-hint" aria-hidden="true">{step.hint}</small> : null}
      </button>
    })}
  </div>
  return <div className="app-shell"><main>
    <header className="topbar">
      <div className="project-heading"><img src="/logo.png" alt="ComicFlow" width={32} height={32} style={{ objectFit: "contain", flexShrink: 0 }} /><span className="status-dot" />{loadError ? '项目读取失败' : loading ? '正在读取项目…' : snapshot ? '项目已加载' : '尚未选择项目'}
        {snapshot && <span className="current-project-title" aria-label="当前项目" title={projectTitle(snapshot)}>{projectTitle(snapshot)}</span>}
        {snapshot && <span className="session-status" aria-label="项目制作状态">{productionStatus}</span>}
        {credits !== null && <span className="credit-badge">{credits} Credits</span>}
        {loadError && onReload && <button onClick={onReload}>重新读取项目</button>}
      </div>
      <div className="top-actions">
        <button onClick={() => setProjectOpen(true)}>打开已有项目</button>
        {automatic && session.error && <span role="alert" className="session-error">会话读取失败，请刷新后核对状态。</span>}
        {automatic && session.data && !snapshot?.exportManifest && <div className="session-controls" aria-label="生成会话控制">
          <span className="session-status">{waitingAdoption ? canResume ? '已采用，等待手动继续' : '视频已生成，等待采用' : `${stageLabels[session.data.stage] ?? '自动制作'} · ${sessionLabels[session.data.status] ?? '请核对任务状态'}`}</span>
          {waitingAdoption && <button onClick={() => {
            if (session.data?.waitingShotId) setSelectedShotId(session.data.waitingShotId)
            setActiveModule('visuals')
          }}>查看待采用镜头</button>}
          {session.data.status === 'paused'
            ? <button disabled={sessionBusy || session.isError || !canResume} onClick={() => sessionAction.mutate('resume')}>继续</button>
            : !stopped && <button disabled={sessionBusy || session.isError} onClick={() => sessionAction.mutate('pause')}>暂停</button>}
          {session.data.status === 'waiting-retry' && <button disabled={sessionBusy || session.isError} onClick={() => sessionAction.mutate('retry')}>重试</button>}
          {session.data.mode === 'automatic' && !stopped && (beforeConfirm
            ? <span className="session-hint">先到「剧本」工作区拆分并确认</span>
            : <button title="推进下一生产步骤，可能调用模型并消耗额度" onClick={() => advance.mutate()} disabled={sessionBusy || session.isError || session.data.status === 'paused'}>推进</button>)}
          {sessionBusy && <span role="status">正在处理…</span>}
        </div>}
        {actionError && <span role="alert" className="session-error">{actionError instanceof Error ? actionError.message : '操作失败，请核对会话状态。'}</span>}
        <button title="模型 API 设置" onClick={() => setModelOpen(true)}><Settings2 size={16} /> 模型 API</button>
        {snapshot?.project && <button title="登录并认领项目" onClick={() => setClaimOpen(true)}>登录/认领</button>}
      </div>
    </header>
    <div className={`workspace ${activeModule === 'create' ? 'workspace-create' : 'workspace-module'}`}>
      {activeModule === 'create' ? <div className="studio-shell">{nav}{children}</div>
        : <div className="workbench-frame"><div className="workbench-toolbar">{nav}</div><div className="workbench-content">{children}</div></div>}
    </div>
  </main>
    {modelOpen && <ModelApiSettings onClose={() => setModelOpen(false)} />}
    {projectOpen && <ProjectPicker onClose={() => setProjectOpen(false)} />}
    {claimOpen && snapshot?.project && <ClaimProjectDialog projectId={snapshot.project.id} onClose={() => setClaimOpen(false)} onClaimed={(_userId, available) => { setCredits(available); setClaimOpen(false) }} />}
  </div>
}
