import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Layers, RefreshCw } from 'lucide-react'
import { useEffect, useState } from 'react'
import { comicflowApi } from '../../api/client'
import { useWorkspace } from '../../stores/workspace'
import { readProductionReadiness } from '../../production-readiness'
import { ShotPoster } from '../../components/ShotPoster'
import { useBatchGeneration } from '../../use-batch-generation'
import type { Snapshot } from '../../types'
import { EmptyWorkspace } from '../script/ScriptWorkspace'
import { VisualPreparation } from './VisualPreparation'
import { VideoJobPanel } from './VideoJobPanel'
import { videoJobActive, videoJobStages } from '../../video-jobs'

/** The valid asset for a shot, if it has been generated. */
function visualFor(snapshot: Snapshot, shotId: string): Record<string, unknown> | undefined {
  return snapshot.visualAssets.find((asset) => asset.shotId === shotId && asset.valid)
}

export function VisualWorkspace({ snapshot }: { snapshot?: Snapshot }) {
  const [showCurrent, setShowCurrent] = useState(false)
  const { projectId, selectedShotId, setSelectedShotId } = useWorkspace()
  const queryClient = useQueryClient()
  const shots = snapshot?.script?.shots ?? []
  const selected = shots.find((shot) => shot.id === selectedShotId) ?? shots[0]
  const [continuityChoices, setContinuityChoices] = useState<Record<string, 'auto' | 'previous-tail'>>({})
  const choiceKey = `${projectId}/${selected?.id}`
  const continuityMode = continuityChoices[choiceKey] ?? 'auto'
  const readiness = readProductionReadiness(snapshot)
  const batch = useBatchGeneration(snapshot)
  const jobs = useQuery({
    queryKey: ['video-jobs', projectId],
    queryFn: () => comicflowApi.videoJobs(projectId!),
    enabled: Boolean(projectId), retry: false, refetchInterval: 2500,
  })
  const currentJob = jobs.data?.find(job => job.shotId === selected?.id)
  const activeJobs = jobs.data?.filter(videoJobActive) ?? []
  useEffect(() => {
    if (jobs.data?.some(job => job.status === 'succeeded')) {
      void queryClient.invalidateQueries({ queryKey: ['snapshot', projectId] })
      void queryClient.invalidateQueries({ queryKey: ['visual-preflight', projectId] })
    }
  }, [jobs.data, projectId, queryClient])
  const preparation = useQuery({
    queryKey: ['visual-preflight', projectId, selected?.id, snapshot?.project.version, snapshot?.visualAssets, continuityMode],
    queryFn: () => comicflowApi.previewVisual(projectId!, selected!.id, snapshot!.project.version, continuityMode),
    enabled: Boolean(projectId && selected && snapshot),
    retry: false,
    refetchOnWindowFocus: false,
  })
  const generate = useMutation({
    mutationFn: () => comicflowApi.queueVideo(projectId!, selected.id, snapshot!.project.version, preparation.data?.fingerprint ?? undefined, undefined, continuityMode),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ['video-jobs', projectId] })
    },
  })

  if (!selected || !snapshot) return <EmptyWorkspace title="尚未生成画面" />

  const asset = visualFor(snapshot, selected.id)
  const candidate = snapshot.visualAssets.find(item => item.id === currentJob?.result?.assetId
    && item.shotId === selected.id && item.status === 'candidate' && !item.valid)
  const previewAsset = showCurrent && asset ? asset : candidate ?? asset
  const previewingCandidate = Boolean(candidate && previewAsset === candidate)
  const previewUrl = typeof previewAsset?.downloadUrl === 'string' ? previewAsset.downloadUrl : undefined
  const isVideo = previewAsset?.mediaType === 'video'
  const busy = generate.isPending || batch.run.isPending
  const jobsUnavailable = !jobs.data || Boolean(jobs.error)
  const shotBlocked = activeJobs.some(job => job.shotId === selected.id)
  const ready = preparation.data?.ready && preparation.data.fingerprint && !preparation.isFetching && !preparation.error
  const batchLabel = batch.run.isPending
    ? `生成中 ${batch.progress?.done ?? 0}/${batch.progress?.total ?? 0}`
    : `生成全部 (${readiness.missingVisual.length})`

  return (
    <div className="visual-layout">
      <aside className="shot-rail">
        <div className="column-title">
          <strong>动态镜头</strong>
          <span>{readiness.visualDone}/{shots.length}</span>
        </div>
        {readiness.missingVisual.length > 0 && (
          <button className="rail-command" onClick={() => batch.run.mutate('visual')} disabled={busy || jobsUnavailable || activeJobs.length > 0}>
            <Layers size={14} />
            {batchLabel}
          </button>
        )}
        {shots.map((shot) => (
          <button
            key={shot.id}
            className={shot.id === selected.id ? 'selected' : ''}
            onClick={() => { generate.reset(); setShowCurrent(false); setSelectedShotId(shot.id) }}
            disabled={generate.isPending || batch.run.isPending}
          >
            <span className={`shot-thumb tone-${shot.order % 4}`}><ShotPoster snapshot={snapshot} shotId={shot.id} /></span>
            <span>
              <strong>{String(shot.order).padStart(2, '0')} {shot.title}</strong>
              <small>{activeJobs.find(job => job.shotId === shot.id) ? videoJobStages[activeJobs.find(job => job.shotId === shot.id)!.status] : snapshot.visualAssets.some(a => a.shotId === shot.id && a.status === 'candidate' && !a.valid) ? '候选待确认' : visualFor(snapshot, shot.id) ? '已采用' : '等待生成'}</small>
            </span>
          </button>
        ))}
      </aside>
      <section className="visual-stage">
        <div className="editor-toolbar">
          <div>
            <strong>动态镜头预览</strong>
            <span>{previewingCandidate ? '候选视频 · 尚未用于当前镜头' : asset ? '当前资产 · 实际尺寸与帧率尚未检测' : '生成前请核对右侧准备单'}</span>
          </div>
          {candidate && asset && <button onClick={() => setShowCurrent(value => !value)}>
            {showCurrent ? '查看候选视频' : '查看当前采用视频'}
          </button>}
        </div>
        {previewUrl && isVideo ? (
          <video className="video-canvas" src={previewUrl} controls playsInline />
        ) : previewUrl ? (
          <img className="video-canvas" src={previewUrl} alt={selected.title} />
        ) : (
          <div className={`video-canvas tone-${selected.order % 4}`}>
            <span>{selected.title}</span>
            <small>尚无画面。先检查准备单，再提交生成。</small>
          </div>
        )}
        <div className="generation-strip">
          <span>
            <strong>{selected.action}</strong>
            <small>{selected.emotion} · {selected.shotSize} · {selected.durationSec}s{candidate ? ' · 候选待确认' : ''}</small>
          </span>
          <button onClick={() => generate.mutate()} disabled={busy || jobsUnavailable || shotBlocked || !ready || Boolean(generate.error)}>
            <RefreshCw size={15} />
            {generate.isPending ? '提交作业中…' : asset ? '重新生成' : '生成当前镜头'}
          </button>
        </div>
        {batch.progress?.error && <small role="alert">批量生成中断：{batch.progress.error}</small>}
        {batch.progress?.waitingShotId && !jobs.data?.find(job => job.shotId === batch.progress?.waitingShotId)?.result?.adopted && <p role="status">
          {batch.progress.current}已生成，等待采用；后续镜头尚未提交。
          <button onClick={() => { setShowCurrent(false); setSelectedShotId(batch.progress!.waitingShotId!) }}>查看待采用镜头</button>
        </p>}
        {generate.error && <small role="alert">{(generate.error as Error).message}</small>}
        {jobs.isPending && <p role="status">正在读取已保存任务…</p>}
        {jobs.error && <p role="alert">任务记录读取失败：{jobs.error.message}。为避免重复提交，暂时不能生成。</p>}
        <button className="video-job-command" onClick={() => { void jobs.refetch() }} disabled={jobs.isFetching}>刷新任务记录</button>
        {currentJob && <VideoJobPanel key={currentJob.id} job={currentJob} candidate={candidate} />}
        {batch.run.isPending && <button className="video-job-command" onClick={batch.stop}>停止后续镜头</button>}
        <p className="generation-note">新视频会先作为候选，确认后再采用。</p>
      </section>
      <aside className="inspector visual-inspector" aria-label="生成准备单">
        <div className="inspector-head">
          <strong>生成准备单</strong>
          <button onClick={() => { generate.reset(); void preparation.refetch() }} disabled={busy || preparation.isFetching}>刷新准备单</button>
        </div>
        <label>镜头接续<select aria-label="镜头接续" value={continuityMode} disabled={busy || shotBlocked}
          onChange={event => { generate.reset(); setContinuityChoices(values => ({ ...values, [choiceKey]: event.target.value as 'auto' | 'previous-tail' })) }}>
          <option value="auto">常规参考 · 保留角色参考图</option>
          <option value="previous-tail">连续动作 · 上一镜头尾帧作首帧</option>
        </select></label>
        {continuityMode === 'previous-tail' && <p className="preflight-warning">适用于同场景连续动作。严格首帧不能同时传角色参考图；新角色入场宜用常规参考。</p>}
        {preparation.isFetching && <p role="status">正在检查保存的输入，不调用生成模型…</p>}
        {preparation.error && <p role="alert">准备单读取失败：{(preparation.error as Error).message}。请刷新后再生成。</p>}
        {preparation.data && <VisualPreparation data={preparation.data} />}
        <label>
          已保存的视觉描述（只读）
          <textarea value={selected.visualDescription} readOnly />
        </label>
        <div className="metric-list">
          <div>
            <span>资产类型</span>
            <strong>{previewAsset ? (isVideo ? '视频' : '静态画面') : '—'}</strong>
          </div>
          <div>
            <span>资产记录时长</span>
            <strong>{previewAsset?.durationMs ? `${Math.round(Number(previewAsset.durationMs) / 100) / 10}s` : previewAsset?.durationSec ? `${previewAsset.durationSec}s` : '未知'}</strong>
          </div>
          <div>
            <span>已生成资产模型</span>
            <strong>{String(previewAsset?.modelVersion ?? previewAsset?.model ?? '未知')}</strong>
          </div>
        </div>
      </aside>
    </div>
  )
}
