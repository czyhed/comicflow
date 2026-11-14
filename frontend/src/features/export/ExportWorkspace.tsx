import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { AlertTriangle, Check, Download, Film, Play, RefreshCw } from 'lucide-react'
import { ApiError, comicflowApi } from '../../api/client'
import { useWorkspace } from '../../stores/workspace'
import { describeMissing, readProductionReadiness } from '../../production-readiness'
import type { Snapshot } from '../../types'
import { EmptyWorkspace } from '../script/ScriptWorkspace'

type Manifest = Awaited<ReturnType<typeof comicflowApi.exportPackage>>

function explain(error: unknown): string {
  const code = error instanceof Error ? error.message : '操作失败，请核对任务状态。'
  const messages: Record<string, string> = {
    ASSETS_INCOMPLETE: '还有镜头缺少素材，请先完成下方缺失项目。',
    COMPOSITION_SHOTS_INVALID: '请选择有效且不重复的镜头。',
    COMPOSITION_TRIM_INVALID: '裁剪区间无效，请检查镜头、入点与出点。',
    INSUFFICIENT_CREDIT: '项目额度不足，无法开始合成。',
    VERSION_CONFLICT: '项目已被修改，请刷新后核对最新内容。',
    COMPOSITION_AUDIO_MISSING: '视频没有声音轨道，但剧本包含台词。已有视频已保留，未调用配音模型。',
    COMPOSITION_MEDIA_UNREADABLE: '合成素材读取失败，请核对文件是否仍存在。',
    COMPOSITION_VIDEO_TOO_SHORT: '视频长度不足，请核对镜头时长或裁剪出点。',
    PROVIDER_TIMEOUT: '请求超时，请先刷新并核对已有任务，不要连续提交。',
  }
  return messages[code] ?? code
}

export function ExportWorkspace({ snapshot }: { snapshot?: Snapshot }) {
  if (!snapshot?.script) return <EmptyWorkspace title="尚未准备导出" />
  return <Delivery key={snapshot.project.id} snapshot={snapshot} />
}

function Delivery({ snapshot }: { snapshot: Snapshot }) {
  const { setActiveModule, setSelectedShotId } = useWorkspace()
  const queryClient = useQueryClient()
  const [manifest, setManifest] = useState<Manifest | null>(null)
  const [tab, setTab] = useState<'video' | 'cover' | 'subtitles'>('video')
  const [downloadStatus, setDownloadStatus] = useState('')
  const [mediaFailed, setMediaFailed] = useState(false)
  const [mode, setMode] = useState<'full' | 'selected'>('full')
  const allReadiness = readProductionReadiness(snapshot)
  const available = allReadiness.shots.filter(shot => !allReadiness.missingVisual.includes(shot) && !allReadiness.missingAudio.includes(shot))
  const [selectedIds, setSelectedIds] = useState<string[]>(() => available.map(shot => shot.id))
  const [exportId, setExportId] = useState('')
  const [shotTrims, setShotTrims] = useState<Record<string, { inSec: number; outSec: number }>>({})
  const [trimShotId, setTrimShotId] = useState('')
  const [mediaDurations, setMediaDurations] = useState<Record<string, number>>({})
  const sourcePlayer = useRef<HTMLVideoElement>(null)
  const partial = mode === 'selected'
  const selectedShots = allReadiness.shots.filter(shot => selectedIds.includes(shot.id))
  const videoShots = selectedShots.filter(shot => snapshot.visualAssets.some(a => a.shotId === shot.id && a.valid && a.mediaType === 'video'))
  const trimShot = videoShots.find(shot => shot.id === trimShotId) ?? videoShots[0]
  const trimAsset = snapshot.visualAssets.find(a => a.shotId === trimShot?.id && a.valid && a.mediaType === 'video')
  const trimDuration = trimShot ? mediaDurations[trimShot.id] ?? (Number(trimAsset?.durationMs) / 1000 || trimShot.durationSec) : 0
  const trim = trimShot ? shotTrims[trimShot.id] ?? { inSec: 0, outSec: Math.min(trimShot.durationSec, trimDuration) } : { inSec: 0, outSec: 0 }
  const activeTrims = Object.fromEntries(Object.entries(shotTrims).filter(([sid]) => selectedIds.includes(sid)))
  const invalidTrims = Object.entries(activeTrims).some(([sid, value]) => !Number.isFinite(value.inSec) || !Number.isFinite(value.outSec) || value.inSec < 0 || value.outSec <= value.inSec || value.outSec > (mediaDurations[sid] ?? Infinity))
  const updateTrim = (value: Partial<typeof trim>) => { if (trimShot) setShotTrims(current => ({ ...current, [trimShot.id]: { ...trim, ...value } })) }
  const readiness = partial ? readProductionReadiness({ ...snapshot, script: { ...snapshot.script!, shots: selectedShots } }) : allReadiness
  const scopedJobs = snapshot.jobs.filter(item => item.type === 'composition' && Boolean(item.shotIds) === partial)
  const job = scopedJobs.at(-1)
  const exports = scopedJobs.filter(item => item.status === 'succeeded' && item.exportManifest)
  const selectedExport = exports.find(item => item.id === exportId) ?? exports.at(-1)
  const ready = partial ? Boolean(selectedExport) : Boolean(snapshot.exportManifest)
  const activeJob = snapshot.jobs.some(item => item.type === 'composition' && (item.status === 'queued' || item.status === 'running'))
  const readExport = () => comicflowApi.exportPackage(snapshot.project.id, partial ? selectedExport?.id : undefined)
  const files = partial ? selectedExport?.exportManifest?.files : snapshot.exportManifest?.files
  const exportKey = partial ? selectedExport?.id : JSON.stringify(snapshot.exportManifest)
  useEffect(() => { setManifest(null); setMediaFailed(false); setDownloadStatus('') }, [mode, exportKey])
  const compose = useMutation({
    mutationFn: () => comicflowApi.requestComposition(snapshot.project.id, snapshot.project.version, partial ? selectedIds : undefined, partial ? activeTrims : undefined),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['snapshot', snapshot.project.id] }),
  })
  const preview = useMutation({
    mutationFn: readExport,
    onSuccess: result => { setManifest(result); setMediaFailed(false) },
  })
  const download = useMutation({
    mutationFn: readExport,
    onSuccess: result => {
      const videoUrl = result.downloadUrl ?? result.downloads?.['video.mp4']
      const anchor = document.createElement('a')
      const objectUrl = videoUrl ? null : URL.createObjectURL(new Blob([JSON.stringify(result, null, 2)], { type: 'application/json' }))
      anchor.href = videoUrl ?? objectUrl!
      anchor.download = videoUrl ? `${result.projectId}${partial ? '-preview' : ''}.mp4` : `${result.projectId}-export-manifest.json`
      if (videoUrl) { anchor.target = '_blank'; anchor.rel = 'noopener noreferrer' }
      document.body.appendChild(anchor)
      anchor.click()
      anchor.remove()
      if (objectUrl) window.setTimeout(() => URL.revokeObjectURL(objectUrl), 0)
      setDownloadStatus(videoUrl ? '已发起视频下载，请查看浏览器下载或新标签页。' : '已发起导出清单下载；该清单暂未提供视频下载地址。')
    },
  })
  const videoUrl = manifest?.downloadUrl ?? manifest?.downloads?.['video.mp4']
  const coverUrl = manifest?.downloads?.['cover.jpg']
  const subtitleUrl = manifest?.downloads?.['subtitles.srt']
  const navigate = (module: 'visuals' | 'audio', shotId?: string) => {
    if (shotId) setSelectedShotId(shotId)
    setActiveModule(module)
  }
  const missing = readiness.missingVisual.length + readiness.missingAudio.length
  const serverMissing = compose.error instanceof ApiError ? compose.error.missingVisualShotIds : []

  return <div className="export-layout">
    <section className="export-preview">
      <div className="editor-toolbar"><div><strong>{partial ? '试片预览' : '导出包预览'}</strong><span>{ready ? '已有导出文件' : '等待合成'}</span></div></div>
      {ready ? <>
        <div className="delivery-preview-actions">
          <button onClick={() => preview.mutate()} disabled={preview.isPending}>{preview.isPending ? '读取中…' : manifest ? '刷新预览地址' : '加载成片预览'}</button>
          {manifest && <div className="mini-tabs" role="tablist" aria-label="导出文件">
            {(['video', 'cover', 'subtitles'] as const).map((item, index) => <button key={item} role="tab" aria-selected={tab === item}
              className={tab === item ? 'active' : ''} onClick={() => { setTab(item); setMediaFailed(false) }}>{['视频', '封面', '字幕'][index]}</button>)}
          </div>}
        </div>
        <div className="delivery-canvas">
          {!manifest ? <p>点击“加载成片预览”读取已有文件。</p>
            : tab === 'video' ? videoUrl ? <video aria-label="合成视频预览" src={videoUrl} controls playsInline preload="metadata" onError={() => setMediaFailed(true)} /> : <p>导出记录暂未提供视频地址。</p>
              : tab === 'cover' ? coverUrl ? <img alt="合成视频封面" src={coverUrl} onError={() => setMediaFailed(true)} /> : <p>导出记录暂未提供封面地址。</p>
                : <div><p>字幕来自剧本与镜头时长，尚未进行语音时间对齐。</p>{subtitleUrl ? <a href={subtitleUrl} target="_blank" rel="noopener noreferrer" download="subtitles.srt">查看或下载 SRT 字幕</a> : <p>导出记录暂未提供字幕地址。</p>}</div>}
        </div>
      </> : <div className="delivery-canvas"><div className="delivery-empty"><Film size={32} /><p>合成完成后，可在这里预览视频、封面和字幕。</p></div></div>}
      {preview.error && <p role="alert" className="error-banner">{explain(preview.error)}</p>}
      {mediaFailed && <p role="alert" className="error-banner">文件加载失败，请刷新预览地址；若仍失败，请核对文件是否存在。</p>}
      <div className="quality-row">
        <span>画面 {readiness.visualDone}/{readiness.shots.length}</span>
        <span>视频原声来源 {readiness.nativeAudioShots.length} 个镜头</span>
        <span>独立配音 {readiness.audioDone}/{readiness.audioNeeded}</span>
      </div>
      <p className="delivery-note">原声音轨在合成时检查。字幕为剧本草稿，不代表已经逐句对齐或完成声音质量验收。</p>
    </section>
    <aside className="delivery-panel">
      <div className="mini-tabs composition-modes" role="tablist" aria-label="合成范围">
        <button role="tab" aria-selected={!partial} disabled={preview.isPending || download.isPending || compose.isPending} className={!partial ? 'active' : ''} onClick={() => { setMode('full'); compose.reset() }}>完整成片</button>
        <button role="tab" aria-selected={partial} disabled={preview.isPending || download.isPending || compose.isPending} className={partial ? 'active' : ''} onClick={() => { setMode('selected'); compose.reset() }}>选中镜头</button>
      </div>
      {partial && <div className="delivery-block composition-selection">
        <label>镜头选择 · 已选 {selectedShots.length}/{allReadiness.shots.length}</label>
        <div className="composition-selection-actions">
          <button onClick={() => setSelectedIds(available.map(shot => shot.id))}>选择已就绪</button>
          <button onClick={() => setSelectedIds([])}>清空</button>
        </div>
        <div className="composition-shot-list">
          {allReadiness.shots.map(shot => {
            const canSelect = available.includes(shot)
            return <label key={shot.id} className={`composition-shot ${canSelect ? '' : 'unavailable'}`}>
              <input type="checkbox" aria-label={`合成镜头 ${shot.order} ${shot.title}`} checked={selectedIds.includes(shot.id)} disabled={!canSelect || compose.isPending || activeJob}
                onChange={event => setSelectedIds(ids => event.target.checked ? [...ids, shot.id] : ids.filter(id => id !== shot.id))} />
              <span>{shot.order}. {shot.title}<small>{canSelect ? `${shot.durationSec}s` : allReadiness.missingVisual.includes(shot) ? '缺已采用画面' : '缺配音'}</small></span>
            </label>
          })}
        </div>
        {trimShot && <details className="composition-trim" open>
          <summary>镜头裁剪</summary>
          <select aria-label="裁剪镜头" value={trimShot.id} disabled={compose.isPending || activeJob} onChange={event => setTrimShotId(event.target.value)}>
            {videoShots.map(shot => <option key={shot.id} value={shot.id}>{shot.order}. {shot.title}</option>)}
          </select>
          {typeof trimAsset?.downloadUrl === 'string' && <video key={trimShot.id} ref={sourcePlayer} aria-label="裁剪原视频" src={trimAsset.downloadUrl} controls playsInline preload="metadata"
            onTimeUpdate={event => { if (event.currentTarget.dataset.trimPreview === 'true' && event.currentTarget.currentTime >= trim.outSec) { event.currentTarget.pause(); delete event.currentTarget.dataset.trimPreview } }}
            onLoadedMetadata={event => { const duration = event.currentTarget.duration; if (Number.isFinite(duration)) setMediaDurations(values => ({ ...values, [trimShot.id]: duration })) }} />}
          <div className="composition-trim-points">
            <label>入点（秒）<input aria-label="裁剪入点" type="number" min="0" step="0.1" value={Number.isFinite(trim.inSec) ? trim.inSec : ''} disabled={compose.isPending || activeJob}
              onChange={event => updateTrim({ inSec: event.target.valueAsNumber })} /></label>
            <label>出点（秒）<input aria-label="裁剪出点" type="number" min="0" max={trimDuration} step="0.1" value={Number.isFinite(trim.outSec) ? trim.outSec : ''} disabled={compose.isPending || activeJob}
              onChange={event => updateTrim({ outSec: event.target.valueAsNumber })} /></label>
          </div>
          <div className="composition-selection-actions">
            <button title="播放保留区间" disabled={invalidTrims || !trimAsset?.downloadUrl} onClick={() => { const video = sourcePlayer.current; if (video) { video.currentTime = trim.inSec; video.dataset.trimPreview = 'true'; void video.play().catch(() => { delete video.dataset.trimPreview }) } }}><Play size={14} /> 预览裁剪</button>
            <button title="将当前播放位置设为入点" disabled={compose.isPending || activeJob || !trimAsset?.downloadUrl} onClick={() => updateTrim({ inSec: Math.round((sourcePlayer.current?.currentTime ?? 0) * 100) / 100 })}>设为入点</button>
            <button title="将当前播放位置设为出点" disabled={compose.isPending || activeJob || !trimAsset?.downloadUrl} onClick={() => updateTrim({ outSec: Math.round((sourcePlayer.current?.currentTime ?? 0) * 100) / 100 })}>设为出点</button>
            <button disabled={compose.isPending || activeJob} onClick={() => setShotTrims(values => Object.fromEntries(Object.entries(values).filter(([sid]) => sid !== trimShot.id)))}>重置</button>
          </div>
          <small>原视频 {trimDuration.toFixed(2)}s · 保留 {Math.max(0, trim.outSec - trim.inSec).toFixed(2)}s{shotTrims[trimShot.id] ? ' · 已设置' : ''}</small>
          {invalidTrims && <p role="alert" className="error-banner">裁剪区间无效，请检查入点、出点和视频长度。</p>}
        </details>}
        {exports.length > 0 && <label>已保存试片<select aria-label="已保存试片" disabled={preview.isPending || download.isPending} value={selectedExport?.id ?? ''} onChange={event => setExportId(event.target.value)}>
          {exports.map((item, index) => <option key={item.id} value={item.id}>试片 {index + 1} · {item.shotIds?.length} 个镜头</option>)}
        </select></label>}
      </div>}
      <div className={`delivery-status ${ready ? 'ready' : ''}`}><span>{ready ? <Check size={18} /> : <Film size={18} />}</span><div>
        <strong>{ready ? '导出包已就绪' : activeJob ? '合成处理中' : job?.status === 'failed' ? '合成失败' : missing ? '素材尚未准备完成' : '可以开始合成'}</strong>
        <small>{ready ? '可读取已有文件进行预览和下载。' : missing ? describeMissing(readiness) : '合成已有素材，保留 H3 视频原声，不调用生成模型。'}</small>
      </div></div>
      {!ready && missing > 0 && <div className="delivery-block" aria-label="缺失资产清单">
        <label>待准备素材</label>
        {readiness.missingVisual.slice(0, 6).map(shot => <div className="file-row" key={`v-${shot.id}`}><AlertTriangle size={14} />{shot.order}. {shot.title} · 缺画面</div>)}
        {readiness.missingAudio.slice(0, 6).map(shot => <div className="file-row" key={`a-${shot.id}`}><AlertTriangle size={14} />{shot.order}. {shot.title} · 缺独立配音</div>)}
        {missing > 12 && <small>其余缺失镜头请在对应工作区查看。</small>}
        {readiness.missingVisual.length > 0 && <button onClick={() => navigate('visuals', readiness.missingVisual[0].id)}>去准备画面</button>}
        {readiness.missingAudio.length > 0 && <button onClick={() => navigate('audio', readiness.missingAudio[0].id)}>去准备独立配音</button>}
      </div>}
      <div className="delivery-block"><label>交付文件</label>
        {['video.mp4', 'cover.jpg', 'subtitles.srt'].map(filename => <div className="file-row" key={filename}>{filename}<span>{files?.includes(filename) ? '已有记录' : '待合成'}</span></div>)}
        {manifest?.format && <p>导出记录规格：{manifest.format}</p>}
      </div>
      {ready && <button className="delivery-command" onClick={() => download.mutate()} disabled={download.isPending}>
        <Download size={16} />{download.isPending ? '正在准备下载…' : '下载导出包'}
      </button>}
      {(!ready || partial) && <button className="delivery-command" onClick={() => compose.mutate()} disabled={!readiness.composable || compose.isPending || activeJob || (partial && invalidTrims)}>
        <RefreshCw size={16} />{activeJob ? '合成处理中' : compose.isPending ? '正在提交…' : partial ? '合成选中镜头' : '开始合成'}
      </button>}
      {compose.error && <p role="alert" className="error-banner">{explain(compose.error)}{serverMissing.length > 0 && ` · 缺画面镜头：${serverMissing.join('、')}`}</p>}
      {!ready && job?.status === 'failed' && <p role="alert" className="error-banner">{explain(new Error(job.error ?? '合成失败，请核查已有任务。'))}</p>}
      {download.error && <p role="alert" className="error-banner">{explain(download.error)}</p>}
      {downloadStatus && <p role="status">{downloadStatus}</p>}
    </aside>
  </div>
}
