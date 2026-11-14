import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { request } from '../../api/client'
import { useWorkspace } from '../../stores/workspace'
import type { Snapshot } from '../../types'

type Resource = {
  id: string; kind: 'shot' | 'export'; title: string; projectTitle: string
  shotId: string | null; sourceAvailable: boolean; status: string
  createdAt: string | null; model: string | null; durationMs: number | null
  fileState: 'unchecked' | 'untracked'
}
type Access = { url: string; posterUrl: string | null; filename: string; expiresAt: string }
const states: Record<string, string> = { current: '正在使用', historical: '历史版本', candidate: '候选', stale: '输入已变化' }
const errors: Record<string, string> = {
  RESOURCE_FILE_MISSING: '文件缺失，历史记录仍保留。',
  RESOURCE_FILE_UNTRACKED: '没有保存的视频文件，需要核查原任务。',
  RESOURCE_STORAGE_UNAVAILABLE: '暂时无法访问视频存储，请稍后重新获取链接。',
  RESOURCE_NOT_FOUND: '这条资源记录已不可用，请刷新列表。',
  PROJECT_ACCESS_DENIED: '没有访问这个项目的权限。',
}

function ResourceAccess({ projectId, item, download }: { projectId: string; item: Resource; download: boolean }) {
  const [playbackError, setPlaybackError] = useState(false)
  const access = useQuery({
    queryKey: ['video-resource-access', projectId, item.id, download],
    queryFn: () => request<Access>(`/api/projects/${encodeURIComponent(projectId)}/video-resources/${encodeURIComponent(item.id)}/access?download=${download}`),
    retry: false, staleTime: 0, gcTime: 0, refetchOnWindowFocus: false,
  })
  // Hide a previously signed URL while renewing it or after a failed renewal.
  const data = !access.isFetching && !access.error ? access.data : undefined
  return <section className="resource-preview" aria-label="选中视频">
    <h3>{item.title} · {download ? '下载' : '预览'}</h3>
    <p>查看历史版本不会替换当前镜头。</p>
    {access.isFetching && <p role="status">正在检查文件并获取链接…</p>}
    {access.error && <p role="alert">{errors[access.error.message] ?? '无法读取视频，请刷新后重试。'}</p>}
    {data && (download
      ? <a className="resource-download" href={data.url} download={data.filename} target="_blank" rel="noreferrer">保存视频文件</a>
      : <video key={data.url} aria-label="历史视频预览" controls playsInline preload="metadata"
        src={data.url} poster={data.posterUrl ?? undefined} onError={() => setPlaybackError(true)} />)}
    {data && <p className="muted">链接有效期至 {new Date(data.expiresAt).toLocaleTimeString()}；过期后可重新获取。</p>}
    {playbackError && !download && <p role="alert">视频暂时无法播放，可能是链接过期、网络或格式问题。可重新获取链接，不会重新生成。</p>}
    <button disabled={access.isFetching} onClick={() => { setPlaybackError(false); void access.refetch() }}>
      {download ? '重新获取下载链接' : '重新获取播放链接'}
    </button>
  </section>
}

function ProjectVideoResources({ snapshot }: { snapshot: Snapshot }) {
  const projectId = snapshot.project.id
  const { setActiveModule, setSelectedShotId } = useWorkspace()
  const [kind, setKind] = useState('all')
  const [status, setStatus] = useState('all')
  const [shotId, setShotId] = useState('')
  const [offset, setOffset] = useState(0)
  const [selected, setSelected] = useState<{ item: Resource; download: boolean } | null>(null)
  const params = new URLSearchParams({ kind, status, offset: String(offset), limit: '24' })
  if (shotId) params.set('shot_id', shotId)
  const list = useQuery({
    queryKey: ['video-resources', projectId, kind, status, shotId, offset],
    queryFn: () => request<{ items: Resource[]; total: number; limit: number }>(`/api/projects/${encodeURIComponent(projectId)}/video-resources?${params}`),
    retry: false, refetchOnWindowFocus: false,
  })
  const change = (setter: (value: string) => void, value: string) => {
    setter(value); setOffset(0); setSelected(null)
  }
  return <section className="resource-workspace">
    <header className="resource-heading"><div><h2>视频资源</h2><p>当前项目 · {snapshot.script?.title ?? '未命名项目'} · 浏览和下载不调用模型</p></div>
      <button disabled={list.isFetching} onClick={() => { setSelected(null); void list.refetch() }}>刷新资源</button>
    </header>
    <div className="resource-filters">
      <label>类型<select aria-label="资源类型" value={kind} onChange={e => change(setKind, e.target.value)}>
        <option value="all">全部视频</option><option value="shot">镜头视频</option><option value="export">合成成片</option>
      </select></label>
      <label>镜头<select aria-label="资源镜头" value={shotId} onChange={e => change(setShotId, e.target.value)}>
        <option value="">全部镜头</option>{snapshot.script?.shots.map(s => <option key={s.id} value={s.id}>{s.title}</option>)}
      </select></label>
      <label>状态<select aria-label="视频状态" value={status} onChange={e => change(setStatus, e.target.value)}>
        <option value="all">全部状态</option>{Object.entries(states).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
      </select></label>
    </div>
    <p className="muted">按已记录的生成时间倒序排列；时间未知的旧记录列在后面。合成成片目前只保留当前版本。</p>
    {list.isPending && <p role="status">正在读取视频资源…</p>}
    {list.error && <p role="alert">资源列表读取失败，请点击刷新资源重试。</p>}
    {!list.error && list.data && <>
      <p aria-live="polite">共 {list.data.total} 个视频</p>
      {!list.data.items.length && <p>当前筛选下没有视频。已有的视频会在这里保留记录。</p>}
      <div className="resource-grid">{list.data.items.map(item => <article className="resource-card" key={item.id}>
        <div className="resource-card-label">{item.kind === 'export' ? '合成成片' : '镜头视频'} · {states[item.status] ?? '状态未知'}</div>
        <h3>{item.title}</h3>
        <p>{item.model ?? '模型未知'} · {item.durationMs ? `${item.durationMs / 1000} 秒` : '时长未知'}</p>
        <p>{item.createdAt ? new Date(item.createdAt).toLocaleString() : '生成时间未知'}</p>
        {item.fileState === 'untracked' && <p>未保存文件，需要核查原任务</p>}
        <div className="resource-actions">
          <button aria-label={`预览 ${item.title}`} onClick={() => setSelected({ item, download: false })}>预览</button>
          <button aria-label={`下载 ${item.title}`} onClick={() => setSelected({ item, download: true })}>下载</button>
          <button aria-label={`来源镜头 ${item.title}`} disabled={!item.sourceAvailable} onClick={() => {
            if (item.kind === 'export') setActiveModule('export')
            else if (item.shotId) { setSelectedShotId(item.shotId); setActiveModule('visuals') }
          }}>{item.sourceAvailable ? item.kind === 'export' ? '查看导出' : '来源镜头' : '来源不可用'}</button>
        </div>
      </article>)}</div>
      <nav className="resource-pages" aria-label="资源分页">
        <button disabled={offset === 0 || list.isFetching} onClick={() => { setOffset(Math.max(0, offset - 24)); setSelected(null) }}>上一页</button>
        <span>第 {Math.floor(offset / 24) + 1} 页</span>
        <button disabled={offset + 24 >= list.data.total || list.isFetching} onClick={() => { setOffset(offset + 24); setSelected(null) }}>下一页</button>
      </nav>
    </>}
    {selected && <ResourceAccess key={`${selected.item.id}-${selected.download}`} projectId={projectId} {...selected} />}
  </section>
}

export function VideoResourcesWorkspace({ snapshot }: { snapshot?: Snapshot }) {
  return snapshot ? <ProjectVideoResources key={snapshot.project.id} snapshot={snapshot} />
    : <section className="resource-workspace"><h2>视频资源</h2><p>请先创建或打开项目，再查看已有视频。</p></section>
}
